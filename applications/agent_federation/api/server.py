import asyncio
import json
import os
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(find_dotenv())

from agent_core.logging import get_logger
from agent_core.tracing import init_tracing, start_span

logger = get_logger(__name__)

# 持有后台任务引用，避免 CPython 在任务完成前回收 coroutine frame 导致静默丢失
_background_tasks: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

from api.monitor import manager

API_KEY = os.getenv("API_KEY", "")
ZHIKU_API_URL = os.getenv("ZHIKU_API_URL", "")

from api.auth import resolve_thread_id

_HAS_SECURITY_GUARDS = False
try:
    from agent_core.guardrails.web import SecurityGuardsMiddleware
    _HAS_SECURITY_GUARDS = True
except ImportError:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    init_tracing(service_name="deepagents")

    from agent.tracing.langfuse_adapter import init_langfuse, is_langfuse_enabled
    init_langfuse()
    if is_langfuse_enabled():
        logger.info("Langfuse 已启用，trace 将上报 Langfuse")
    else:
        logger.info("Langfuse 未配置，trace 走 agent-core OTel（开发期 no-op 降级）")

    # zhiku 健康探活（异步，不阻塞启动）
    if ZHIKU_API_URL:
        import threading

        from tools.zhiku_tools import check_zhiku_health
        threading.Thread(target=check_zhiku_health, daemon=True).start()

    # 子服务健康探活（Phase 2 联邦网关）
    from agent.health_check import start_health_check
    start_health_check()

    # 类型化记忆 pgvector 连接池（ADR-0003 单一 psycopg 池，遵守 ADR-0004）
    from agent.db import init_pool

    await init_pool()

    logger.info("deepagents 服务启动完成")

    # P1.1：lifespan 预初始化 main_agent，消除并发首请求的重复构造竞态。
    # 预初始化失败不致命：run_deep_agent 仍会经 _main_agent_lock 懒加载兜底。
    try:
        from agent.main_agent import get_main_agent
        await get_main_agent()
        logger.info("main_agent 预初始化完成（lifespan）")
    except Exception as e:
        logger.warning("main_agent 预初始化失败（非致命，首次请求懒加载兜底）: %s", e)

    # P1.3：启动 checkpoint 定时清理后台任务（复用 main_agent 的 checkpointer）。
    # InMemorySaver 时返回 None（无需清理）；其他异常不影响主服务。
    _cleaner_task = None
    try:
        from agent.checkpoint_cleaner import start_checkpoint_cleaner
        from agent.main_agent import get_main_checkpointer
        _cleaner_task = await start_checkpoint_cleaner(get_main_checkpointer())
    except Exception as e:
        logger.warning("checkpoint 清理任务启动失败（非致命）: %s", e)

    yield

    # P1.3：关闭时取消清理任务
    if _cleaner_task is not None:
        try:
            from agent.checkpoint_cleaner import stop_checkpoint_cleaner
            await stop_checkpoint_cleaner(_cleaner_task)
        except Exception as e:
            logger.warning("checkpoint 清理任务停止异常: %s", e)

    from agent.tracing.langfuse_adapter import shutdown_langfuse
    shutdown_langfuse()

    from agent.db import close_pool

    await close_pool()


app = FastAPI(title="DeepAgents API", lifespan=lifespan)

output_dir = project_root / "output"
output_dir.mkdir(exist_ok=True)

updated_dir = project_root / "updated"
updated_dir.mkdir(exist_ok=True)

_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins if _allowed_origins else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

_ALLOW_NO_AUTH = os.getenv("DISABLE_AUTH", "false").lower() in ("1", "true", "yes")

if _HAS_SECURITY_GUARDS and API_KEY:
    app.add_middleware(
        SecurityGuardsMiddleware,
        api_key=API_KEY,
        rate_limit_per_client=int(os.getenv("RATE_LIMIT_PER_CLIENT", "30")),
        rate_limit_global=int(os.getenv("RATE_LIMIT_GLOBAL", "200")),
        exempt_paths=("/health", "/ws/"),
    )
elif _ALLOW_NO_AUTH:
    logger.warning(
        "安全告警：已显式禁用认证 (DISABLE_AUTH=true)，服务对所有请求开放，"
        "仅限隔离开发环境使用，禁止在生产部署。"
    )
else:
    logger.warning(
        "安全告警：未配置 API_KEY 且未显式设置 DISABLE_AUTH=true，"
        "服务将拒绝所有未携带正确 API_KEY 的请求 (返回 401)。"
        "生产部署请设置 API_KEY；本地开发可设 DISABLE_AUTH=true。"
    )

    @app.middleware("http")
    async def _require_api_key(request: Request, call_next):  # type: ignore[name-defined]
        if request.url.path in ("/health", "/ws/"):
            return await call_next(request)
        if not API_KEY:
            # 本分支表示未配置 API_KEY 且未显式 DISABLE_AUTH，一律拒绝
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"detail": "API key required (server misconfigured)"})
        auth = request.headers.get("Authorization", "")
        provided = auth[len("Bearer ") :] if auth.lower().startswith("bearer ") else auth
        if secrets.compare_digest(provided, API_KEY):
            return await call_next(request)
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"detail": "API key required"})

_concurrency_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_TASKS", "10")))


def _extract_api_key(request: Request) -> str | None:
    """从请求头提取 API_KEY 原文（与 _require_api_key 校验逻辑一致）。"""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[len("Bearer ") :]
    return request.headers.get("X-API-Key") or None


def _check_api_key(key: str | None) -> bool:
    # 未配置 API_KEY 且未显式禁用认证时，fail-closed：拒绝所有请求（含 WebSocket）
    if not API_KEY:
        return _ALLOW_NO_AUTH
    return secrets.compare_digest(key or "", API_KEY)


def _sanitize_filename(name: str) -> str:
    base = Path(name).name
    safe = re.sub(r'[^\w.\- ]', '_', base)
    if safe in (".", ".."):
        safe = "_"
    return safe


class TaskRequest(BaseModel):
    query: str
    thread_id: str = None


from agent.main_agent import run_deep_agent


@app.post("/api/task")
async def run_task(request: TaskRequest):
    # 安全：API_KEY 启用时忽略客户端 thread_id，按密钥派生稳定会话（防劫持 + 跨请求续接）
    api_key = _extract_api_key(request)
    thread_id = resolve_thread_id(request.thread_id, api_key)
    with start_span("api.task", attrs={"thread_id": thread_id}):
        async def _run():
            async with _concurrency_semaphore:
                await run_deep_agent(request.query, workspace_id=thread_id)

        _track_task(asyncio.create_task(_run()))
        return {"status": "started", "thread_id": thread_id}


@app.post("/api/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    thread_id: str = Form(None),
    request: Request = None,
):
    # 安全：API_KEY 启用时忽略客户端 thread_id，按密钥派生，保证上传文件落到与对话同一会话目录
    api_key = _extract_api_key(request) if request else None
    safe_thread_id = resolve_thread_id(thread_id, api_key)
    target_dir = updated_dir / f"session_{_sanitize_filename(safe_thread_id)}"
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for file in files:
        safe_name = _sanitize_filename(file.filename or "unnamed")
        file_path = target_dir / safe_name
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_files.append(safe_name)

    return {"status": "uploaded", "files": saved_files}


@app.get("/api/download")
async def download_file(path: str):
    try:
        abs_path = Path(path).resolve()
        output_abs = output_dir.resolve()
        if not abs_path.is_relative_to(output_abs):
            return {"error": "拒绝访问: 只能下载输出目录下的文件"}
    except Exception:
        return {"error": "无效的路径参数"}
    if not abs_path.exists():
        return {"error": "文件不存在"}
    return FileResponse(abs_path, filename=abs_path.name)


@app.get("/api/files")
async def list_files(path: str):
    try:
        abs_path = Path(path).resolve()
        output_abs = output_dir.resolve()
        if not abs_path.is_relative_to(output_abs):
            return {"error": "拒绝访问: 只能访问输出目录下的文件"}
    except Exception as e:
        return {"error": f"路径无效: {e}"}
    if not abs_path.exists():
        return {"error": "目录不存在"}
    files = []
    try:
        for file_path in abs_path.rglob("*"):
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "name": file_path.name,
                    "type": "file",
                    "path": str(file_path),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime
                })
    except Exception as e:
        return {"error": str(e)}
    files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return {"files": files}


@app.get("/metrics")
async def metrics_endpoint():
    """P3 可观测性：暴露进程内指标快照（JSON）。

    含熔断器计数/状态与子 Agent 委派结果计数。零 prometheus 依赖，
    符合内核零依赖铁律；需标准 scraping 时可在此桥接 OpenTelemetry exporter。
    """
    from agent.metrics import snapshot

    return snapshot()


@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    thread_id: str,
    api_key: str | None = Query(None, alias="api_key"),
):
    if not _check_api_key(api_key):
        await websocket.close(code=4001, reason="Invalid API key")
        return
    # 认证启用时忽略 URL 中的 thread_id（不可信），按密钥派生，使 WS 桥接到与 /api/task 同一会话
    ws_thread_id = resolve_thread_id(thread_id, api_key)
    await manager.connect(websocket, ws_thread_id)
    try:
        # Plan-F WS 出口统一：客户端发 {"type":"query","text":...} → 服务端经
        # AgenticPlanner.execute 产出 StreamEvent（与 app /query 同构）→ 逐条 send_json。
        # 传输层 WS 与 app SSE 不同，但事件 schema 经共享 serialize_stream_event 同源。
        from agent_federation.planners import AgenticPlanner, get_planner_runtime
        from agent_runtime.planner.protocol import (
            PlannerContext,
            serialize_stream_event,
        )

        planner = AgenticPlanner()
        runtime = get_planner_runtime()

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "error": "invalid json"})
                continue

            if msg.get("type") != "query" or not msg.get("text"):
                await websocket.send_json({"type": "pong", "message": f"服务端已收到: {data}"})
                continue

            plan = await planner.plan(PlannerContext(question=msg["text"], workspace_id=ws_thread_id))
            final_answer = ""
            async for event in planner.execute(plan, runtime):
                out = serialize_stream_event(event)
                if out is None:
                    continue
                if event.type == "answer":
                    final_answer = event.payload.get("text", "")
                await websocket.send_json(out)
            await websocket.send_json({"type": "done", "thread_id": ws_thread_id, "answer": final_answer})
    except WebSocketDisconnect:
        manager.disconnect(websocket, ws_thread_id)
    except Exception:
        manager.disconnect(websocket, ws_thread_id)


if __name__ == "__main__":
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
