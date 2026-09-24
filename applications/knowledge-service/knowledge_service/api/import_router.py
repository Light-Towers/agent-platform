# -*- coding: utf-8 -*-
"""
文件导入路由（从原 file_import_service.py 抽取为 FastAPI 子路由）。

职责：
- /import.html：返回文件导入前端页面；
- /upload：接收多文件上传 → 本地落盘 → MinIO 持久化 → 启动 LangGraph 后台导入任务；
- /status/{task_id}：查询单个任务的实时进度与全局状态。

跨域（CORS）统一在 knowledge_service.main.create_app() 中配置，本路由不再单独处理。
"""

import os
import shutil
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
from knowledge_service.utils.path_util import PROJECT_ROOT
from knowledge_service.utils.task_utils import (
    add_done_task,
    add_running_task,
    get_done_task_list,
    get_running_task_list,
    get_task_status,
    update_task_status,
)

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
        with open(local_file_abs_path, "wb") as file_buffer:
            shutil.copyfileobj(file.file, file_buffer)
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
                minio_client.fput_object(
                    bucket_name=minio_bucket_name,
                    object_name=minio_object_name,
                    file_path=local_file_abs_path,
                    content_type=file.content_type,
                )
                logger.info(f"[{task_id}] 文件已成功上传至MinIO，桶名：{minio_bucket_name}，对象名：{minio_object_name}")
                break
            except Exception as e:
                if attempt < _MINIO_RETRIES:
                    import time
                    time.sleep(1 << attempt)  # 1s, 2s
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

    # 9. 所有文件处理完毕，返回上传成功信息和所有TaskID（前端基于TaskID轮询进度）
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
