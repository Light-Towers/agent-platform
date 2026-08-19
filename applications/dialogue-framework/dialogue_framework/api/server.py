"""FastAPI 异步 server：对话服务入口。

与 app/main.py 风格一致：lifespan 初始化 Store/Retriever/LLM，
POST /query 路由复用 shared-schemas 契约，LLM 失败 → fallback=true 降级。
"""

import time
from contextlib import asynccontextmanager

from agent_core.logging import get_logger
from fastapi import FastAPI, Request
from shared_schemas import HealthResponse, HealthStatus, QueryRequest, QueryResponse

from dialogue_framework.agent.agent import DialogueAgent
from dialogue_framework.agent.message_processor import MessageProcessor
from dialogue_framework.core.stores.tracker_store import build_store
from dialogue_framework.shared.config import get_settings

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = await build_store()
    agent = DialogueAgent(store=store)
    app.state.processor = MessageProcessor(agent=agent)
    app.state.settings = settings
    logger.info(
        "dialogue-framework 就绪 host=%s port=%d store=%s llm=%s",
        settings.host,
        settings.port,
        settings.store_backend,
        settings.llm_enabled,
    )
    yield


async def handle_query(request: QueryRequest, http_request: Request) -> QueryResponse:
    start = time.perf_counter()
    processor = http_request.app.state.processor
    session_id = request.session_id or request.tenant_id or "default"

    try:
        result = await processor.process(session_id, request.query)
        latency = (time.perf_counter() - start) * 1000
        return QueryResponse(
            answer=result["response"],
            intent=result.get("intent"),
            fallback=result.get("fallback", False),
            latency_ms=round(latency, 2),
            trace_id=request.trace_id,
        )
    except Exception:
        logger.exception("query handler failed")
        latency = (time.perf_counter() - start) * 1000
        return QueryResponse(
            answer="抱歉，处理时发生错误，请稍后重试。",
            fallback=True,
            latency_ms=round(latency, 2),
            trace_id=request.trace_id,
        )


async def handle_health(http_request: Request) -> HealthResponse:
    return HealthResponse(status=HealthStatus.HEALTHY, version="0.1.0", dependencies=[])


def create_app() -> FastAPI:
    app = FastAPI(title="dialogue-framework", version="0.1.0", lifespan=lifespan)
    app.post("/query", response_model=QueryResponse)(handle_query)
    app.get("/health", response_model=HealthResponse)(handle_health)
    return app


app = create_app()
