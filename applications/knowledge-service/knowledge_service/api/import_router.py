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

from knowledge_service.clients.milvus_utils import get_milvus_client

# 项目内部工具/配置/客户端
from knowledge_service.clients.minio_utils import get_minio_client
from knowledge_service.conf.milvus_config import milvus_config
from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger  # 项目统一日志工具
from knowledge_service.import_process.agent.main_graph import kb_import_app  # LangGraph全流程编译实例
from knowledge_service.import_process.agent.state import get_default_state
from knowledge_service.utils import kb_collections, kb_delete, kb_doc_count, kb_upload_history
from knowledge_service.utils.kb_registry import (
    delete_document as delete_document_registry,
)
from knowledge_service.utils.kb_registry import (
    get_document,
    list_by_tenant,
    update_status,
    upsert_by_upload,
)
from knowledge_service.utils.lifecycle_reimport import ReimportError, plan_reimport, resolve_original_file
from knowledge_service.utils.path_util import PROJECT_ROOT
from knowledge_service.utils.task_utils import (
    add_done_task,
    add_running_task,
    get_done_task_list,
    get_running_task_list,
    get_task_result,
    get_task_status,
    get_task_summary,
    set_task_result,
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
def _persist_upload_history(
    task_id: str,
    metadata: Optional[Dict[str, Any]],
    status: str,
    error: str,
) -> None:
    """管线结束后把这次上传的元数据 + 切块读数落 Mongo（观测面，失败不拦主流程）。

    落库点选在 run_graph_task 尾部而非 HTTP handler：切块 summary 是管线中途才写入
    task_utils 进程内存的，handler 里还没有；这里 get_task_summary 才拿得到完整读数。
    filename 从 metadata 取（截图/多文件场景），没有就从 local_file_path 取——但本函数
    只拿到 metadata，故 filename 由调用方在 metadata 里透传（见 upload_files 落盘处）。
    """
    meta = dict(metadata or {})
    tenant_id = str(meta.get("tenant_id", "") or "default")
    filename = str(meta.get("filename", "") or meta.get("original_filename", "") or task_id)
    try:
        summary = get_task_summary(task_id)
    except Exception:  # summary 读取失败按空处理（观测面，不拦落库）
        summary = {}
    kb_upload_history.record_upload(
        task_id=task_id,
        tenant_id=tenant_id,
        filename=filename,
        metadata=meta,
        status=status,
        summary=summary,
        error=error,
    )


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
        _persist_upload_history(task_id, metadata, "completed", "")

    except Exception as e:
        # 5. 捕获全流程异常，更新任务全局状态为：失败，并记录错误日志（含堆栈）
        update_task_status(task_id, "failed")
        # error 同时写进 task result：原实现只进日志 ⇒ 前端只知道 failed、不知道为什么，
        # 管理员无从判断是解析失败还是切分/入库失败。set/get_task_result 早就有，
        # 这里只是把那个在册能力接上（不改状态码、不改异常传播语义）。
        # P8（lint_architecture 门禁）：task result / 上传历史经 /status、/history 回前端，
        # 属 API 可见面 ⇒ 不回显异常原文（可能含内部路径）。具体原因只在下方日志（exc_info），
        # 对外给异常类名 + 可行动指引。
        error_kind = type(e).__name__
        set_task_result(task_id, "error", f"处理失败（{error_kind}）；详情见服务端日志")
        logger.error(f"[{task_id}] LangGraph全流程执行失败，异常信息：{str(e)}", exc_info=True)
        _persist_upload_history(task_id, metadata, "failed", error_kind)


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
    knowledge_id: str = Form("", description="知识条目唯一标识（必填：登记/发布/检索的唯一锚点，空值文档无法被检索）"),
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
    # knowledge_id 必填（治本）：它是登记(kb_registry)/发布(reimport)/检索的唯一锚点。
    # 空 ID 的文档会进入「解析完成但无法登记、无法发布、查不出来」的死胡同——
    # 正是"知识图谱文档查不到"的根因。在入口拦下，不带病产生后续任务。
    if not knowledge_id or not knowledge_id.strip():
        raise HTTPException(status_code=422, detail="KNOWLEDGE_ID_REQUIRED：知识库 ID 为必填项，用于文档登记与发布管理")
    knowledge_id = knowledge_id.strip()

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
        #    metadata 按任务复制一份并带 filename：上传历史落库在管线尾部按任务记录文件名，
        #    共享 dict 会让多文件场景的历史全部记成最后一个文件名。
        task_metadata = dict(metadata)
        task_metadata["filename"] = safe_filename
        background_tasks.add_task(run_graph_task, task_id, task_local_dir, local_file_abs_path, task_metadata)
        logger.info(f"[{task_id}] 已将LangGraph全流程加入后台任务，任务已启动")

        # 8.5 P1：确保知识库一等实体存在（kb_collections）。
        #    knowledge_id 为空不建库（与 kb_documents 既有行为一致）；
        #    写失败只落 WARNING 不拦上传（注册表是管理面，不是 upload 闸门）。
        if knowledge_id.strip():
            from knowledge_service.utils import kb_collections
            kb_collections.ensure_collection(
                tenant_id=tenant_id, knowledge_id=knowledge_id, name=knowledge_id.strip()
            )

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
        # 以下两枚是「结果可核对」面（2026-11-16 新增）：
        #   error   —— 失败原因（原实现只进日志 ⇒ 屏上只知 failed 不知为何）
        #   summary —— 切分统计 + 语义结构对照（原实现只进日志/本地 chunks.json）
        # 都是附加字段，原有五个键的形状不变（集成测试钉的那五格仍成立）。
        "error": get_task_result(task_id, "error"),
        "summary": get_task_summary(task_id),
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


@router.get("/documents/tree", summary="知识库文档树（库→文档→切片）")
async def documents_tree():
    """按断言租户从 Milvus v3 集合聚合知识库文档树（真实入库数据）。

    返回 {knowledge_bases:[{knowledge_id, documents:[{source_doc, chunk_count, chunks:[...]}]}]}。
    doc_count = 该库 distinct source_doc 数（前端左栏用），不再读 kb_collections 的恒 0 冗余字段。
    """
    from collections import defaultdict

    tenant_id = resolve_server_tenant("", endpoint="/documents/tree")
    client = get_milvus_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Milvus 不可达，无法读取文档树")
    try:
        rows = client.query(
            collection_name=milvus_config.chunks_collection,
            filter=f'tenant_id == "{tenant_id}"',
            output_fields=["knowledge_id", "source_doc", "part", "title", "parent_title", "content", "status"],
            limit=16384,
        ) or []
    except Exception as e:  # noqa: BLE001 — 具名 502，不吞堆栈
        logger.error("[documents/tree] Milvus 查询失败", exc_info=True)
        raise HTTPException(status_code=502, detail=f"文档树查询失败：{type(e).__name__}") from e

    tree: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        kid = str(r.get("knowledge_id") or "").strip()
        if not kid:
            continue
        source_doc = str(r.get("source_doc") or "").strip() or "未命名文档"
        tree[kid][source_doc].append({
            "part": r.get("part"),
            "title": str(r.get("title") or ""),
            "parent_title": str(r.get("parent_title") or ""),
            "content": str(r.get("content") or ""),
            "status": str(r.get("status") or ""),
        })
    result = []
    for kid, docs in tree.items():
        doc_list = []
        for source_doc, chunks in docs.items():
            chunks.sort(key=lambda c: (c["part"] if isinstance(c["part"], int) else 0))
            doc_list.append({
                "source_doc": source_doc,
                "chunk_count": len(chunks),
                "chunks": chunks,
            })
        result.append({
            "knowledge_id": kid,
            "doc_count": len(doc_list),
            "documents": doc_list,
        })
    result.sort(key=lambda x: x["knowledge_id"])
    return {"code": 200, "tenant_id": tenant_id, "total": len(result), "knowledge_bases": result}


@router.get("/collections", summary="知识库列表", description="按服务端断言租户列出 kb_collections 注册的知识库（updated_at 降序）")
async def list_collections(limit: int = 100):
    """租户内知识库清单（agent_server GET /kb/knowledge-bases 代理到这里）。

    P1 形状对齐原 /documents 聚合结果：knowledge_id / doc_count / status /
    latest_updated_at，另加 name/owner/created_at 供管理页用。
    doc_count 为该库真实文档数（Milvus distinct source_doc 实时聚合），与
    GET /documents/tree 的 doc_count 同口径——对话页下拉与知识库页左栏读同一字段即一致。
    kb_collections 的冗余 doc_count 恒 0（无人维护），不读它。Milvus 不可达降级为 0。
    """
    capped = max(1, min(limit, 100))
    tenant_id = resolve_server_tenant("", endpoint="/collections")
    rows = kb_collections.list_by_tenant(tenant_id, limit=capped)

    # 实时聚合真实文档数：kb_collections 的冗余 doc_count 恒 0，不能给前端用。
    # 与 /documents/tree 的 doc_count 同口径（distinct source_doc），两页读同一端点即一致。
    # Milvus 不可达时降级为全 0（列表本身不拦，检索主链路不为辅助计数买单）。
    doc_counts: dict[str, int] = {}
    client = get_milvus_client()
    if client is not None:
        try:
            doc_counts = kb_doc_count.count_docs_by_kb(
                client, milvus_config.chunks_collection, tenant_id,
            )
        except Exception:  # noqa: BLE001 — 计数是辅助项，失败降级全 0，不吞主流程
            logger.warning("[collections] 文档数聚合失败，降级为 0", exc_info=True)

    items = [
        {
            "knowledge_id": str(r.get("knowledge_id") or ""),
            "name": str(r.get("name") or r.get("knowledge_id") or ""),
            "owner": str(r.get("owner") or ""),
            "status": str(r.get("status") or ""),
            "doc_count": doc_counts.get(str(r.get("knowledge_id") or ""), 0),
            "latest_updated_at": str(r.get("updated_at") or ""),
        }
        for r in rows
    ]
    return {"code": 200, "tenant_id": tenant_id, "total": len(items), "knowledge_bases": items}


@router.post("/collections", summary="新建知识库", status_code=201)
async def create_collection(req: dict):
    """新建空知识库：用户输入 name，系统生成全局唯一 knowledge_id（kb_<uuid>）。

    请求体 {"name": "产品手册"}。name 非空；同名允许（ID 唯一）。
    """
    tenant_id = resolve_server_tenant("", endpoint="POST /collections")
    name = str((req or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="知识库名称不能为空")
    doc = kb_collections.create_collection(tenant_id=tenant_id, name=name)
    if doc is None:
        raise HTTPException(status_code=503, detail="知识库创建失败（存储不可用）")
    logger.info(f"[collections] {tenant_id} 新建知识库 {doc['knowledge_id']} name={name}")
    return {"code": 201, **doc}


@router.patch("/collections/{knowledge_id}", summary="重命名知识库")
async def rename_collection(knowledge_id: str, req: dict):
    """改知识库显示名（不改 knowledge_id）。请求体 {"name": "新名字"}。"""
    tenant_id = resolve_server_tenant("", endpoint="PATCH /collections/{id}")
    name = str((req or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="知识库名称不能为空")
    ok = kb_collections.rename_collection(tenant_id, knowledge_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"知识库不存在或已被删除: {knowledge_id}")
    return {"code": 200, "knowledge_id": knowledge_id, "name": name}


@router.delete("/documents/{knowledge_id}", summary="删除文档（软删除，标记 REVOKED）")
async def delete_document(knowledge_id: str, source_doc: str | None = None):
    """下线文档：其 Milvus 切片 status→REVOKED，检索不再召回。

    source_doc 给定时只下线该文档（三级结构里点单文档删除）；不给则下线整库（旧行为兼容）。
    仅当库下再无非 REVOKED 切片时才把 kb_documents 登记表标 REVOKED。
    租户取服务端断言（X-Internal-Tenant），跨租户删不到；文档不存在时 404。
    可逆：重新走 DRAFT→PUBLISHED 可恢复（新切片 status=PUBLISHED）。
    """
    source_doc = (source_doc or "").strip() or None
    tenant_id = resolve_server_tenant("", endpoint="DELETE /documents/{id}")
    record = get_document(tenant_id, knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未知 knowledge_id（或该条未登记）: {knowledge_id}")
    client = get_milvus_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Milvus 不可达，无法下线文档")

    def _update_registry(t: str, k: str, s: str) -> bool:
        return update_status(tenant_id=t, knowledge_id=k, status=s, task_id="soft-delete")

    try:
        result = kb_delete.revoke_document(
            client, milvus_config.chunks_collection, tenant_id, knowledge_id,
            source_doc=source_doc, update_registry=_update_registry,
        )
    except Exception as e:  # noqa: BLE001 — 具名 502，不吞堆栈
        logger.error(f"[delete] {tenant_id}/{knowledge_id} 下线失败", exc_info=True)
        raise HTTPException(status_code=502, detail=f"文档下线失败：{type(e).__name__}") from e
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"该知识库无 Milvus 切片: {knowledge_id}")
    logger.info(f"[delete] {tenant_id}/{knowledge_id} 软删除：{result['revoked_chunks']} 切片标记 REVOKED")
    return {"code": 200, "knowledge_id": knowledge_id, "status": "REVOKED", **result}


@router.post("/documents/{knowledge_id}/restore", summary="重新上线文档（REVOKED→PUBLISHED，恢复 RAG 召回）")
async def restore_document_endpoint(knowledge_id: str, source_doc: str):
    """把已下线文档的切片改回 PUBLISHED，恢复可被检索召回。source_doc 必填。"""
    source_doc = (source_doc or "").strip()
    if not source_doc:
        raise HTTPException(status_code=400, detail="source_doc 必填")
    tenant_id = resolve_server_tenant("", endpoint="POST /documents/{id}/restore")
    client = get_milvus_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Milvus 不可达，无法上线文档")
    try:
        result = kb_delete.restore_document(
            client, milvus_config.chunks_collection, tenant_id, knowledge_id,
            source_doc=source_doc,
            update_registry=lambda t, k, s: update_status(
                tenant_id=t, knowledge_id=k, status=s, task_id="restore",
            ),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[restore] {tenant_id}/{knowledge_id}/{source_doc} 上线失败", exc_info=True)
        raise HTTPException(status_code=502, detail=f"文档上线失败：{type(e).__name__}") from e
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"没有已下线的文档切片: {source_doc}")
    return {"code": 200, "knowledge_id": knowledge_id, "status": "PUBLISHED", **result}


@router.delete("/documents/{knowledge_id}/purge", summary="真删除文档（物理删切片+登记，不可逆）")
async def purge_document_endpoint(knowledge_id: str, source_doc: str):
    """真删除：物理删该文档全部切片（含 REVOKED）+ 清 kb_documents 登记，不可逆。

    只应对已下线（REVOKED）文档调用——UI 层保证删除按钮只在已下线时出现。
    """
    source_doc = (source_doc or "").strip()
    if not source_doc:
        raise HTTPException(status_code=400, detail="source_doc 必填")
    tenant_id = resolve_server_tenant("", endpoint="DELETE /documents/{id}/purge")
    client = get_milvus_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Milvus 不可达，无法删除文档")
    try:
        result = kb_delete.purge_document(
            client, milvus_config.chunks_collection, tenant_id, knowledge_id,
            source_doc=source_doc,
            delete_registry=lambda t, k: delete_document_registry(tenant_id=t, knowledge_id=k),
        )
    except Exception as e:  # noqa: BLE001
        # 用户视角（2026-11-20）：purge 的副作用是「删 Milvus 切片」，它发生在 registry 回调之前。
        # 若异常发生在切片已删之后（如登记清理/日志），文档其实已经删掉了——此时报 502
        # 会让用户以为失败（而文档已消失），比"多报一次成功"更糟。复查切片确认再定。
        logger.exception(f"[purge] {tenant_id}/{knowledge_id}/{source_doc} 删除过程异常")
        remaining = kb_delete.read_chunks(
            client, milvus_config.chunks_collection, tenant_id, knowledge_id, source_doc=source_doc,
        )
        if not remaining:  # 切片已删干净 ⇒ 删除目标已达成
            return {"code": 200, "knowledge_id": knowledge_id, "status": "PURGED",
                    "deleted_chunks": -1, "note": f"删除已完成，后续步骤异常：{type(e).__name__}"}
        raise HTTPException(status_code=502, detail=f"文档删除失败：{type(e).__name__}") from e
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"文档无切片可删: {source_doc}")
    return {"code": 200, "knowledge_id": knowledge_id, "status": "PURGED", **result}


@router.delete("/collections/{knowledge_id}", summary="删除知识库（前置：库下无有效文档）")
async def delete_collection(knowledge_id: str):
    """删除整个知识库：前置校验库下 Milvus 无有效（非 REVOKED）切片，通过后标 deleted。

    判据以 Milvus 实际切片为准（与页面文档树同源），不再读会漂移的 kb_documents 登记表：
    上传失败卡在 DRAFT/REVIEWING 的空壳库（页面看是无文档的）可直接删。
    软删除：不物理删数据；库 deleted 后不在 /collections 列表出现。跨租户删不到。
    """
    tenant_id = resolve_server_tenant("", endpoint="DELETE /collections/{id}")
    ok, msg = kb_delete.delete_collection_guard(
        tenant_id, knowledge_id,
        client=get_milvus_client(), collection=milvus_config.chunks_collection,
        mark_deleted=kb_collections.mark_deleted,
    )
    if not ok:
        # 区分"有有效文档"（409）与"库不存在 / 校验失败"（404）
        code = 409 if "仍有有效文档" in msg else 404
        raise HTTPException(status_code=code, detail=msg)
    logger.info(f"[delete] {tenant_id}/{knowledge_id} 知识库标记删除")
    return {"code": 200, "knowledge_id": knowledge_id, "status": "deleted", "message": msg}


@router.get("/history", summary="上传历史列表", description="按服务端断言租户列出上传历史（含切块读数，uploaded_at 降序）")
async def list_upload_history(limit: int = 100):
    """租户内上传历史（每次上传一行，切块读数持久化在 Mongo；agent_server GET /kb/history 透传）。

    与 /documents 的区别：documents 只登记 knowledge_id 非空的文档（reimport 依据），
    history 记**每一次上传**（默认 knowledge_id 为空的也算），且带 summary 切块读数——
    这才是「刷新/重启后还能看到上传过什么、怎么切的」的服务端权威面。
    """
    capped = max(1, min(limit, 100))
    tenant_id = resolve_server_tenant("", endpoint="/history")
    items = kb_upload_history.list_by_tenant(tenant_id, limit=capped)
    return {"code": 200, "tenant_id": tenant_id, "total": len(items), "items": items}
