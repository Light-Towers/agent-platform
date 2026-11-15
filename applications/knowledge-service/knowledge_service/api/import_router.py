# -*- coding: utf-8 -*-
"""
文件导入路由（从原 file_import_service.py 抽取为 FastAPI 子路由）。

职责：
- /import.html：返回文件导入前端页面；
- /upload：接收多文件上传 → 本地落盘 → MinIO 持久化 → 启动 LangGraph 后台导入任务；
- /status/{task_id}：查询单个任务的实时进度与全局状态。

跨域（CORS）统一在 knowledge_service.main.create_app() 中配置，本路由不再单独处理。
"""

import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# 第三方库
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

# 项目内部工具/配置/客户端
from knowledge_service.clients.minio_utils import get_minio_client
from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger  # 项目统一日志工具
from knowledge_service.import_process.agent.main_graph import kb_import_app  # LangGraph全流程编译实例
from knowledge_service.import_process.agent.state import get_default_state
from knowledge_service.utils.kb_registry import get_document, list_by_tenant, update_status, upsert_by_upload
from knowledge_service.utils.lifecycle_reimport import ReimportError, plan_reimport, resolve_original_file
from knowledge_service.utils.path_util import PROJECT_ROOT
from knowledge_service.utils.task_utils import (
    add_done_task,
    add_running_task,
    get_done_task_list,
    get_running_task_list,
    get_task_status,
    update_task_status,
)
from knowledge_service.utils.tenant_utils import resolve_server_tenant
from knowledge_service.utils.upload_limit import MAX_UPLOAD_BYTES, UploadTooLarge, copy_with_limit

# 子路由实例：由 create_app() 挂载到根路径
router = APIRouter()


# --------------------------
# 静态页面路由：返回文件导入前端页面import.html
# 访问地址：/import.html
# --------------------------
@router.get("/import.html", response_class=FileResponse)
async def get_import_page():
    """返回文件导入前端页面：import.html"""
    # 拼接HTML文件绝对路径，基于项目根目录定位
    html_abs_path = PROJECT_ROOT / "knowledge_service/import_process/page/import.html"
    # 日志记录页面访问的文件路径，方便排查文件不存在问题
    logger.info(f"前端页面访问，文件绝对路径：{html_abs_path}")

    # 校验文件是否存在，不存在则抛出404异常
    if not os.path.exists(html_abs_path):
        logger.error(f"前端页面文件不存在，路径：{html_abs_path}")
        raise HTTPException(status_code=404, detail="import.html page not found")

    # 以FileResponse返回HTML文件，浏览器自动渲染
    return FileResponse(
        path=html_abs_path,
        media_type="text/html",  # 显式指定媒体类型为HTML，确保浏览器正确解析
    )


# --------------------------
# 后台任务：LangGraph全流程执行
# 独立于主请求线程，由BackgroundTasks触发，避免阻塞接口响应
# --------------------------
def run_graph_task(
    task_id: str,
    local_dir: str,
    local_file_path: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    LangGraph全流程执行后台任务
    核心流程：初始化状态 → 流式执行图节点 → 实时更新任务状态 → 异常捕获
    任务状态更新：pending → processing → completed/failed
    节点进度更新：每完成一个节点，将节点名加入done_list，供前端轮询查看

    :param task_id: 全局唯一任务ID，关联单个文件的全流程处理
    :param local_dir: 该任务的本地文件存储目录（含临时文件/解析结果）
    :param local_file_path: 上传文件的本地绝对路径
    :param metadata: 08+16 通用化 metadata 入参（scope_type/tenant_id/status/...），透传到 state
    """
    try:
        # 1. 更新任务全局状态为：处理中
        update_task_status(task_id, "processing")
        logger.info(f"[{task_id}] 开始执行LangGraph全流程，本地文件路径：{local_file_path}")

        # 2. 初始化LangGraph状态：加载默认状态 + 注入当前任务的核心参数
        init_state = get_default_state()
        init_state["task_id"] = task_id  # 任务ID关联
        init_state["local_dir"] = local_dir  # 任务本地目录
        init_state["local_file_path"] = local_file_path  # 上传文件本地路径
        # 08+16 通用化：透传 metadata 参数化字段（非硬编码）
        if metadata:
            for key in (
                "enable_item_name_recognition",
                "knowledge_id",
                "scope_type",
                "tenant_id",
                "tenant_type",
                "effective_from",
                "effective_to",
                "version",
                "authority",
                "status",
                "constraint_kind",
                "exhibition_id",
                "venue_id",
                "datasource_type",
            ):
                if key in metadata and metadata[key] is not None:
                    init_state[key] = metadata[key]

        # 3. 流式执行LangGraph全流程（stream模式：实时获取每个节点的执行结果）
        for event in kb_import_app.stream(init_state):
            for node_name, node_result in event.items():
                # 记录每个节点完成的日志，包含任务ID和节点名，方便追踪执行顺序
                logger.info(f"[{task_id}] LangGraph节点执行完成：{node_name}")
                # 将完成的节点名加入【已完成列表】，前端轮询/status/{task_id}可实时获取
                add_done_task(task_id, node_name)

        # 4. 全流程执行完成，更新任务全局状态为：已完成
        update_task_status(task_id, "completed")
        logger.info(f"[{task_id}] LangGraph全流程执行完毕，任务完成")

    except Exception as e:
        # 5. 捕获全流程异常，更新任务全局状态为：失败，并记录错误日志（含堆栈）
        update_task_status(task_id, "failed")
        logger.error(f"[{task_id}] LangGraph全流程执行失败，异常信息：{str(e)}", exc_info=True)


# --------------------------
# 核心接口：文件上传接口
# 支持多文件上传，核心流程：接收文件 → 本地保存 → MinIO上传 → 启动后台任务
# 访问地址：/upload （POST请求，form-data格式传参）
# --------------------------
@router.post("/upload", summary="文件上传接口", description="支持多文件批量上传，自动触发知识库导入全流程")
async def upload_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    # 08+16 通用化：metadata 参数化（Form 字段，非硬编码）
    scope_type: str = Form("PRIVATE", description="PUBLIC | PRIVATE，多知识空间隔离"),
    tenant_id: str = Form("", description="租户 ID，多租户隔离（ACL 前置 INV-8）"),
    tenant_type: str = Form("", description="租户类型（enterprise/personal，预留）"),
    effective_from: str = Form("", description="生效起始日 ISO yyyy-MM-dd"),
    effective_to: str = Form("", description="生效截止日 ISO yyyy-MM-dd"),
    version: str = Form("", description="知识版本号"),
    authority: str = Form("", description="发布授权方"),
    status: str = Form("DRAFT", description="生命周期状态 DRAFT/REVIEWING/PUBLISHED/..."),
    constraint_kind: str = Form("", description="约束类型，预留"),
    enable_item_name_recognition: bool = Form(True, description="是否启用商品名 NER 节点"),
    knowledge_id: str = Form("", description="知识条目唯一标识"),
    exhibition_id: str = Form("", description="会展 ID（生命周期校验用）"),
    venue_id: str = Form("", description="场馆 ID（生命周期校验用）"),
    datasource_type: str = Form("", description="数据源类型（mysql/hive），文档归属的数据源类型"),
):
    """
    文件上传核心接口
    1. 接收前端上传的多文件（PDF/MD为主）
    2. 按「日期/任务ID」分层保存到本地输出目录，避免文件冲突
    3. 将文件上传至MinIO对象存储，做持久化保存
    4. 为每个文件生成唯一TaskID，启动独立的LangGraph后台处理任务
    5. 实时更新任务状态，供前端轮询监控进度

    :param background_tasks: FastAPI后台任务对象，用于异步执行LangGraph流程
    :param files: 前端上传的文件列表（form-data格式）
    :return: 包含上传结果和所有任务ID的JSON响应
    """
    # 08+16 通用化：聚合 metadata 入参，透传到后台任务
    # 隔离域（ADR-0006 T11）：tenant 为空时服务端注入默认租户（审计），不再静默全量。
    tenant_id = resolve_server_tenant(tenant_id, endpoint="/upload")
    metadata = {
        "scope_type": scope_type,
        "tenant_id": tenant_id,
        "tenant_type": tenant_type,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "version": version,
        "authority": authority,
        "status": status,
        "constraint_kind": constraint_kind,
        "enable_item_name_recognition": enable_item_name_recognition,
        "knowledge_id": knowledge_id,
        "exhibition_id": exhibition_id,
        "venue_id": venue_id,
        "datasource_type": datasource_type,
    }
    # 1. 构建本地存储根目录：项目根目录/output/YYYYMMDD（按日期分层，方便管理）
    date_based_root_dir = os.path.join(PROJECT_ROOT / "output", datetime.now().strftime("%Y%m%d"))
    # 初始化任务ID列表，用于返回给前端（一个文件对应一个TaskID）
    task_ids = []

    # 2. 遍历处理每个上传的文件（多文件批量处理，各自独立生成TaskID）
    for file in files:
        # 生成全局唯一TaskID（UUID4），作为单个文件的全流程标识
        task_id = str(uuid.uuid4())
        task_ids.append(task_id)
        logger.info(f"[{task_id}] 开始处理上传文件，文件名：{file.filename}，文件类型：{file.content_type}")

        # 3. 标记「文件上传」阶段为「运行中」，前端轮询可查
        add_running_task(task_id, "upload_file")

        # 4. 构建该任务的本地独立目录：output/YYYYMMDD/TaskID，避免多文件重名冲突
        task_local_dir = os.path.join(date_based_root_dir, task_id)
        os.makedirs(task_local_dir, exist_ok=True)  # 目录不存在则创建，存在则不做处理
        # 构建上传文件的本地保存绝对路径（sanitize 防路径遍历）
        # 跨平台统一分隔符：os.path.basename 在 Linux 不剥离 Windows 反斜杠，
        # 先做 replace("\\","/") 保证 basename 正确取末段
        safe_filename = os.path.basename((file.filename or "").replace("\\", "/"))
        if not safe_filename or safe_filename in (".", ".."):
            raise HTTPException(status_code=400, detail="Invalid filename")
        local_file_abs_path = os.path.join(task_local_dir, safe_filename)

        # 5. 将上传的文件保存到本地临时目录（后续MinIO上传/文件解析均基于此文件）
        # 计数分块拷贝（P11 硬校验落点）：边写边数，超 MAX_UPLOAD_BYTES 当场 413——
        # 不整体缓冲进内存，也不写完再判（10GB 级请求不该先占满磁盘）。
        try:
            await asyncio.to_thread(copy_with_limit, file.file, local_file_abs_path, MAX_UPLOAD_BYTES)
        except UploadTooLarge as e:
            logger.warning(f"[{task_id}] 上传被拒（超出上限）：{e}")
            raise HTTPException(status_code=413, detail=f"文件超出上传上限（{MAX_UPLOAD_BYTES // (1024 * 1024)} MB），请拆分后上传") from e
        logger.info(f"[{task_id}] 文件已保存至本地，路径：{local_file_abs_path}")

        # 6. 将本地文件上传至MinIO对象存储，做持久化保存（P2-7: retry + fail-fast）
        # 策略：重试 2 次（1s/2s 退避）后仍失败则拒绝整个上传（避免孤儿处理数据无源可溯）。
        minio_pdf_base_dir = settings.minio_pdf_dir  # 缺省值：pdf_files（见 knowledge_service.core.config）
        # 构建MinIO中的文件对象名：配置目录/YYYYMMDD/文件名（按日期分层，和本地一致）
        minio_object_name = f"{minio_pdf_base_dir}/{datetime.now().strftime('%Y%m%d')}/{safe_filename}"
        minio_client = get_minio_client()
        if minio_client is None:
            raise HTTPException(
                status_code=500, detail="MinIO service connection failed, please check MinIO config"
            )
        minio_bucket_name = settings.minio_bucket_name  # 缺省值：kb-import-bucket

        _MINIO_RETRIES = 2
        for attempt in range(_MINIO_RETRIES + 1):
            try:
                # minio SDK 为同步实现，移入线程池，避免上传阻塞事件循环
                await asyncio.to_thread(
                    minio_client.fput_object,
                    bucket_name=minio_bucket_name,
                    object_name=minio_object_name,
                    file_path=local_file_abs_path,
                    content_type=file.content_type,
                )
                logger.info(f"[{task_id}] 文件已成功上传至MinIO，桶名：{minio_bucket_name}，对象名：{minio_object_name}")
                break
            except Exception as e:
                # 不收窄到 S3Error：minio SDK 连接层错误（urllib3 HTTPError 族）不经 S3Error 包装，
                # 收窄会跳过重试直接冒泡 500；此处统一转 502 信封，堆栈仅落日志
                if attempt < _MINIO_RETRIES:
                    await asyncio.sleep(1 << attempt)  # 1s, 2s
                    logger.warning(f"[{task_id}] MinIO上传第{attempt+1}次失败，重试中: {e}")
                else:
                    logger.error(f"[{task_id}] MinIO上传失败（已重试{_MINIO_RETRIES}次），拒绝本次导入", exc_info=True)
                    raise HTTPException(
                        status_code=502,
                        detail=f"Object storage unavailable: {type(e).__name__}"
                    ) from e

        # 7. 标记「文件上传」阶段为「已完成」，前端轮询可查
        add_done_task(task_id, "upload_file")

        # 8. 将LangGraph全流程处理加入FastAPI后台任务（异步执行，不阻塞当前接口响应）
        background_tasks.add_task(run_graph_task, task_id, task_local_dir, local_file_abs_path, metadata)
        logger.info(f"[{task_id}] 已将LangGraph全流程加入后台任务，任务已启动")

        # 9. 登记 kb_documents 注册表（批 2a）：kb.publish（/reimport）的持久依据。
        #    knowledge_id 为空不登记（保持既有行为；该条不可重提、不出现在 /documents）；
        #    存储失败只落 WARNING 不拦上传（kb_registry 模块头注的三条边界）。
        registered = upsert_by_upload(
            tenant_id=tenant_id,
            knowledge_id=knowledge_id,
            scope_type=scope_type,
            task_id=task_id,
            filename=safe_filename,
            local_dir=task_local_dir,
            local_file_path=local_file_abs_path,
            minio_object=minio_object_name,
            metadata=metadata,
            status=metadata["status"],
        )
        if not registered and knowledge_id.strip():
            logger.warning(f"[{task_id}] kb_documents 登记失败：knowledge_id={knowledge_id} 本次上传不可重提")
        elif not knowledge_id.strip():
            logger.info(f"[{task_id}] knowledge_id 为空，本次上传未登记（不可重提，属既有行为）")

    # 10. 所有文件处理完毕，返回上传成功信息和所有TaskID（前端基于TaskID轮询进度）
    logger.info(f"多文件上传处理完毕，共处理{len(files)}个文件，生成TaskID列表：{task_ids}")
    return {"code": 200, "message": f"Files uploaded successfully, total: {len(files)}", "task_ids": task_ids}


# --------------------------
# 核心接口：任务状态查询接口
# 前端轮询此接口获取单个任务的处理进度和状态
# 访问地址：/status/{task_id} （GET请求）
# --------------------------
@router.get("/status/{task_id}", summary="任务状态查询", description="根据TaskID查询单个文件的处理进度和全局状态")
async def get_task_progress(task_id: str):
    """
    任务状态查询接口
    前端轮询此接口（如每秒1次），获取任务的实时处理进度
    返回数据均来自内存中的任务管理字典（task_utils.py），高性能无IO

    :param task_id: 全局唯一任务ID（由/upload接口返回）
    :return: 包含任务全局状态、已完成节点、运行中节点的JSON响应
    """
    # 构造任务状态返回体
    task_status_info: Dict[str, Any] = {
        "code": 200,
        "task_id": task_id,
        "status": get_task_status(task_id),  # 任务全局状态：pending/processing/completed/failed
        "done_list": get_done_task_list(task_id),  # 已完成的节点/阶段列表
        "running_list": get_running_task_list(task_id),  # 正在运行的节点/阶段列表
    }
    # 记录状态查询日志，方便追踪前端轮询情况
    logger.info(
        f"[{task_id}] 任务状态查询，当前状态：{task_status_info['status']}，已完成节点：{task_status_info['done_list']}"
    )
    return task_status_info


# --------------------------
# 重提入库接口（批 2a 新增；kb.publish 的 KS 上游，agent_server PATCH /kb/{knowledge_id}/status 转发到这里）
# 语义：按已登记文档的持久记录，把原文按**新状态**重跑整条导入管线（解析→分块→向量化→Milvus）。
# 为什么是"重跑"而不是"改状态"：DRAFT 文档当年根本没写进生产 Milvus（node_import_milvus 跳过），
# 状态字段只活在 chunk 标量与注册表里 ⇒ 改一个字段救不回一篇没入库的文档，只有按新状态重跑才有意义。
# 决策面（迁移校验/metadata 合并/PUBLISHED 前置校验/原文定位）在 utils/lifecycle_reimport.py
# 纯函数层——本端点只留接线薄壳（tests/unit 零重型依赖契约，见该模块头注）。
# --------------------------
@router.post("/reimport", summary="按 knowledge_id 重提入库", description="把已登记文档按新生命周期状态重跑导入管线（提审→发布的落点）")
async def reimport_document(
    background_tasks: BackgroundTasks,
    knowledge_id: str = Form(..., description="上传时登记的知识条目唯一标识"),
    status: str = Form(..., description="目标状态 REVIEWING 或 PUBLISHED（走 VALID_TRANSITIONS 合法迁移）"),
    authority: str = Form("", description="覆盖发布授权方（PUBLISHED 前置校验用，空=沿用登记值）"),
    effective_from: str = Form("", description="覆盖生效起始日 ISO yyyy-MM-dd（空=沿用登记值）"),
    effective_to: str = Form("", description="覆盖生效截止日 ISO yyyy-MM-dd（空=沿用登记值）"),
):
    """
    重提入库核心接口（批 2a，薄壳）：
    1. 租户取服务端断言（X-Internal-Tenant 经 TenantHeaderMiddleware 绑定）；**不收 Form tenant_id**——
       与 /upload 的收口不同：这里没有历史包袱，归属从第一天就只认断言（R5 的 KS 侧形状）。
    2. 注册表查 (tenant, knowledge_id)：缺 ⇒ 404（未知 id 或该条未登记，不静默回落）。
    3. 决策面：plan_reimport（VALID_TRANSITIONS + PUBLISHED 前置校验）→ resolve_original_file
       （409/502 具名），ReimportError → HTTPException 同形状转出。
    4. 新 task 目录 → 重跑 run_graph_task（metadata 覆写 status 与三字段）。
    5. 注册表回写 status/task_id/updated_at + 审计日志一行。
    """
    tenant_id = resolve_server_tenant("", endpoint="/reimport")
    record = get_document(tenant_id, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未知 knowledge_id（或该条未登记，无法重提）: {knowledge_id}")
    frm = record.get("status") or "DRAFT"

    try:
        metadata = plan_reimport(
            record,
            tenant_id=tenant_id,
            status=status,
            authority=authority,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        # 新任务目录 + 原文定位（409/502 在 resolve_original_file 里具名抛出）
        task_id = str(uuid.uuid4())
        date_based_root_dir = os.path.join(PROJECT_ROOT / "output", datetime.now().strftime("%Y%m%d"))
        task_local_dir = os.path.join(date_based_root_dir, task_id)
        os.makedirs(task_local_dir, exist_ok=True)
        local_file_abs_path = await asyncio.to_thread(resolve_original_file, record, task_local_dir, get_minio_client())
    except ReimportError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    background_tasks.add_task(run_graph_task, task_id, task_local_dir, local_file_abs_path, metadata)

    update_status(tenant_id=tenant_id, knowledge_id=knowledge_id, status=status, task_id=task_id)
    # 审计留痕（谁、哪条、从哪迁到哪、落在哪个 task）——一行可 grep 的具名日志
    logger.info(
        f"[lifecycle] tenant={tenant_id} knowledge_id={knowledge_id} {frm}→{status} task_id={task_id}（重提入库）"
    )
    return {
        "code": 200,
        "knowledge_id": knowledge_id,
        "from": frm,
        "to": status,
        "task_id": task_id,
        "message": "重提已受理，进度经 /status/{task_id} 轮询",
    }


@router.get("/documents", summary="登记文档列表", description="按服务端断言租户列出 kb_documents 登记文档（updated_at 降序）")
async def list_documents(limit: int = 100):
    """租户内登记文档列表（kb.upload 方向的读面；agent_server GET /kb/documents 透传到这里）。"""
    capped = max(1, min(limit, 100))  # 上限 100：列表面不做分页，量级由导出脚本另行处理
    tenant_id = resolve_server_tenant("", endpoint="/documents")
    docs = list_by_tenant(tenant_id, limit=capped)
    return {"code": 200, "tenant_id": tenant_id, "total": len(docs), "documents": docs}
