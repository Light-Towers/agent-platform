"""应用工厂与生命周期：lifespan 内完成连接池 + 图的预热构建。

所有全局资源在 lifespan 一次性初始化（带锁），请求路径零懒加载竞态。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import build_graph
from app.agent.llm import build_chat_model
from app.api.routes import router
from app.config import get_settings
from app.infra.admission import AdmissionQueue, RateLimiter
from app.infra.coordinator import SessionCoordinator
from app.infra.db import close_pool, get_pool, init_pool
from app.infra.mcp_client import MCPClientManager
from app.infra.otel import force_flush as otel_force_flush
from app.infra.otel import get_otel_tracer, init_otel
from app.infra.revert import RevertHandler
from app.infra.tracing import get_langfuse_callbacks
from app.schemas import McpServerConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _build_checkpointer():
    """有 DATABASE_URL 用 Postgres checkpoint；否则内存版（开发模式）。"""
    settings = get_settings()
    if settings.db_enabled:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = AsyncPostgresSaver.from_conn_string(settings.database_url)
        await saver.setup()
        return saver
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_pool()
    checkpointer = await _build_checkpointer()
    llm = build_chat_model()

    # Phase 2: 会话并发协调
    if settings.coordination_enabled:
        app.state.coordinator = SessionCoordinator(
            policy=settings.coordination_policy,
            enabled=True,
        )
    else:
        app.state.coordinator = None

    # Phase 2: durable admission（opt-in + DATABASE_URL 双重开关）
    if settings.admission_effective_enabled:
        limiter = RateLimiter(
            per_user=settings.admission_rate_limit_per_user,
            per_session=settings.admission_rate_limit_per_session,
            global_=settings.admission_rate_limit_global,
        )
        admission_queue = AdmissionQueue(
            pool=get_pool(),
            capacity=settings.admission_queue_capacity,
            timeout_seconds=settings.admission_queue_timeout_seconds,
            rate_limiter=limiter,
            effective_enabled=True,
        )
        recovered = await admission_queue.recover_on_startup()
        if recovered:
            logger.info("admission recovered %d interrupted requests", recovered)
        app.state.admission_queue = admission_queue
    else:
        app.state.admission_queue = None

    # Phase 2: 会话回退 revert
    if settings.revert_enabled:
        app.state.revert_handler = RevertHandler(checkpointer, get_pool())
    else:
        app.state.revert_handler = None

    # Phase 2: OTel 接线（opt-in）
    if settings.otel_effective_enabled:
        init_otel(
            exporter=settings.otel_exporter,
            endpoint=settings.otel_endpoint,
            sampling_rate=settings.otel_sampling_rate,
            service_name=settings.otel_service_name,
        )
        app.state.otel_tracer = get_otel_tracer()
    else:
        app.state.otel_tracer = None

    # Phase 2: MCP client（opt-in）
    mcp_manager = None
    if settings.mcp_enabled and settings.mcp_servers:
        try:
            import json

            configs = [McpServerConfig(**c) for c in json.loads(settings.mcp_servers)]
            mcp_manager = MCPClientManager(
                server_configs=configs,
                pool=get_pool(),
                breaker_failure_threshold=settings.breaker_failure_threshold,
                breaker_recovery_seconds=settings.breaker_recovery_seconds,
            )
            await mcp_manager.connect_all()
        except Exception:
            logger.warning("MCP init failed, degrading", exc_info=True)
            mcp_manager = None
    app.state.mcp_manager = mcp_manager

    app.state.graph = build_graph(llm, checkpointer=checkpointer, mcp_manager=mcp_manager)
    app.state.checkpointer = checkpointer
    app.state.callbacks = get_langfuse_callbacks()
    logger.info(
        "agent-platform 就绪 storage=%s llm=%s pool=%s coordination=%s admission=%s revert=%s otel=%s mcp=%s",
        "postgres" if settings.db_enabled else "memory",
        settings.llm_enabled,
        get_pool() is not None,
        settings.coordination_enabled,
        settings.admission_effective_enabled,
        settings.revert_enabled,
        settings.otel_effective_enabled,
        mcp_manager is not None,
    )
    yield
    # Phase 2: OTel flush
    otel_force_flush()
    # Phase 2: MCP close
    mcp_mgr = getattr(app.state, "mcp_manager", None)
    if mcp_mgr is not None:
        await mcp_mgr.close_all()
    checkpointer = getattr(app.state, "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    if conn is not None and hasattr(conn, "close"):
        try:
            close_result = conn.close()
            if hasattr(close_result, "__await__"):
                await close_result
        except Exception:  # noqa: BLE001 关闭失败不阻塞退出
            logger.warning("checkpointer 连接关闭失败")
    await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="agent-platform", version="0.1.0", lifespan=lifespan)
    # CORS：允许前端跨域调用 /query 等接口；allow_origins 应从环境变量注入，
    # 默认为回环，避免开发期浏览器被阻断的同时不暴露给任意来源。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip()
            for o in (get_settings().cors_allow_origins or "http://127.0.0.1:5173").split(",")
            if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
