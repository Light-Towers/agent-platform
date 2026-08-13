import asyncio
import os
import re
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, File, Form, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(find_dotenv())

from agent_core.logging import get_logger
from agent_core.tracing import init_tracing, start_span

logger = get_logger(__name__)

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

from api.monitor import manager

API_KEY = os.getenv("API_KEY", "")
ZHIKU_API_URL = os.getenv("ZHIKU_API_URL", "")

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

    logger.info("deepagents 服务启动完成")
    yield

    from agent.tracing.langfuse_adapter import shutdown_langfuse
    shutdown_langfuse()


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

if _HAS_SECURITY_GUARDS and API_KEY:
    app.add_middleware(
        SecurityGuardsMiddleware,
        api_key=API_KEY,
        rate_limit_per_client=int(os.getenv("RATE_LIMIT_PER_CLIENT", "30")),
        rate_limit_global=int(os.getenv("RATE_LIMIT_GLOBAL", "200")),
        exempt_paths=("/health", "/ws/"),
    )

_concurrency_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_TASKS", "10")))


def _check_api_key(key: str | None) -> bool:
    if not API_KEY:
        return True
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
    with start_span("api.task", attrs={"thread_id": request.thread_id or "auto"}):
        # 安全：当 API_KEY 启用时，忽略客户端传入的 thread_id，防止会话劫持
        if API_KEY:
            thread_id = str(uuid.uuid4())
        else:
            thread_id = request.thread_id or str(uuid.uuid4())

        async def _run():
            async with _concurrency_semaphore:
                await run_deep_agent(request.query, thread_id)

        asyncio.create_task(_run())
        return {"status": "started", "thread_id": thread_id}


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...), thread_id: str = Form(...)):
    # 安全：当 API_KEY 启用时，忽略客户端传入的 thread_id，防止会话劫持
    safe_thread_id = str(uuid.uuid4()) if API_KEY else thread_id
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


@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    thread_id: str,
    api_key: str | None = Query(None, alias="api_key"),
):
    if not _check_api_key(api_key):
        await websocket.close(code=4001, reason="Invalid API key")
        return
    await manager.connect(websocket, thread_id)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({
                "type": "pong",
                "message": f"服务端已收到: {data}"
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket, thread_id)
    except Exception:
        manager.disconnect(websocket, thread_id)


if __name__ == "__main__":
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
