"""应用工厂与生命周期：lifespan 内完成连接池 + 图的预热构建。

所有全局资源在 lifespan 一次性初始化（带锁），请求路径零懒加载竞态。
"""

import logging
from contextlib import asynccontextmanager

from agent_runtime.admission import AdmissionQueue, RateLimiter
from agent_runtime.admission_gateway import PgAdmissionController
from agent_runtime.coordinator import SessionCoordinator
from agent_runtime.db import close_pool, get_pool, init_pool
from agent_runtime.mcp_client import MCPClientManager
from agent_runtime.otel import force_flush as otel_force_flush
from agent_runtime.otel import get_otel_tracer, init_otel
from agent_runtime.planner.durability_pg import (
    PgCheckpointStore,
    PgExecutionOwnershipStore,
    PgIdempotencyStore,
)
from agent_runtime.skills.workflow import discover_workflows
from agent_runtime.revert import RevertHandler
from agent_runtime.tracing import get_langfuse_callbacks
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_server.agent.graph import DelegateRef, build_graph
from agent_server.agent.llm import build_chat_model
from agent_server.api.routes import router
from agent_server.config import get_settings
from agent_server.schemas import McpServerConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _build_checkpointer():
    """有 DATABASE_URL 复用 PG 连接池走 Postgres checkpoint；否则内存版（开发模式）。

    统一委托内核 ``get_checkpointer(pg_pool=...)`` 工厂（C8 收口：避免各子包重复
    if MONGO_URL / if DATABASE_URL 样板）。PG 池由 app 自己的 init_pool() 管理，
    仅把池句柄透传给工厂；Mongo/InMemory 分支完全由内核负责降级。
    """
    pool = get_pool()  # db_enabled 为 False 时返回 None → 工厂降级 InMemorySaver
    if pool is None and get_settings().db_enabled:
        raise RuntimeError("db_enabled 但连接池未初始化，检查 lifespan 中 init_pool 顺序")
    from agent_core.memory import get_checkpointer

    saver = get_checkpointer(pg_pool=pool)
    # AsyncPostgresSaver 需要异步建表；InMemorySaver / MongoCheckpointer 无需 setup。
    if pool is not None:
        await saver.setup()
    return saver


def _build_pg_stores(pool):
    """构建 PG 持久化后端（§20.1/20.2）。

    仅在 pool 非 None 时创建；返回 (checkpoint_store, idempotency_store, ownership_store)。
    """
    if pool is None:
        return None, None, None
    checkpoint_store = PgCheckpointStore(pool)
    idempotency_store = PgIdempotencyStore(pool)
    ownership_store = PgExecutionOwnershipStore(pool)
    return checkpoint_store, idempotency_store, ownership_store


def _build_admission_controller(pool, settings):
    """构建 admission 控制器：distributed 模式用 PgAdmissionController，其余用 AdmissionQueue。"""
    if pool is None:
        return None
    if settings.runtime_mode == "distributed":
        return PgAdmissionController(
            pool,
            capacity=settings.admission_queue_capacity,
            timeout_s=settings.admission_queue_timeout_seconds,
        )
    # single_node / local：继续用现有 AdmissionQueue（内存调度 + PG 持久化队列）
    if settings.admission_effective_enabled:
        limiter = RateLimiter(
            per_user=settings.admission_rate_limit_per_user,
            per_session=settings.admission_rate_limit_per_session,
            global_=settings.admission_rate_limit_global,
        )
        return AdmissionQueue(
            pool=pool,
            capacity=settings.admission_queue_capacity,
            timeout_seconds=settings.admission_queue_timeout_seconds,
            rate_limiter=limiter,
            effective_enabled=True,
        )
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # §20 C4: distributed 模式必须有 PG，否则 fail fast
    if settings.runtime_mode == "distributed" and not settings.db_enabled:
        raise RuntimeError(
            "runtime_mode=distributed 要求配置 DATABASE_URL，当前为空。"
            "请设置 DATABASE_URL 或改用 runtime_mode=single_node/local。"
        )

    await init_pool(
        database_url=settings.database_url,
        db_pool_max_size=settings.db_pool_max_size,
    )
    pool = get_pool()
    checkpointer = await _build_checkpointer()

    # §20.1/20.2: 构建 PG 持久化后端
    checkpoint_store, idempotency_store, ownership_store = _build_pg_stores(pool)

    llm = build_chat_model()

    # Phase 2: 会话并发协调
    if settings.coordination_enabled:
        app.state.coordinator = SessionCoordinator(
            policy=settings.coordination_policy,
            enabled=True,
        )
    else:
        app.state.coordinator = None

    # Phase 2: admission 控制器（按 runtime_mode 选择实现）
    admission_controller = _build_admission_controller(pool, settings)
    if admission_controller is not None:
        recovered = await admission_controller.recover_on_startup()
        if recovered:
            logger.info("admission recovered %d interrupted requests", recovered)
        app.state.admission_controller = admission_controller
    else:
        app.state.admission_controller = None

    # Phase 2: 会话回退 revert
    if settings.revert_enabled:
        app.state.revert_handler = RevertHandler(checkpointer, pool)
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
                pool=pool,
                breaker_failure_threshold=settings.breaker_failure_threshold,
                breaker_recovery_seconds=settings.breaker_recovery_seconds,
            )
            await mcp_manager.connect_all()
        except Exception:
            logger.warning("MCP init failed, degrading", exc_info=True)
            mcp_manager = None
    app.state.mcp_manager = mcp_manager

    # delegate_ref 延迟绑定：graph 节点经 runtime.delegate 调用能力（受 skill_guard 组合治理），
    # 解决循环依赖（graph → registry → runtime → graph）——先传空 holder，runtime 创建后填充。
    delegate_ref = DelegateRef()
    app.state.graph = build_graph(
        llm, checkpointer=checkpointer, mcp_manager=mcp_manager, delegate_ref=delegate_ref
    )
    app.state.checkpointer = checkpointer
    # Plan-F Phase 2: Planner 实现（PLANNER env 选择，Phase 3 统一 SSE 出口后供 api 消费）
    # Plan-F Phase 3: PlannerRuntime——注册表注入 graph（含 general_qa Workflow Skill），
    # llm/mcp_manager/pool 一并装配；组合治理（max_skill_depth/max_steps）约束 agentic 路径。
    from agent_runtime.planner.protocol import PlannerRuntime

    from agent_server.capabilities import get_registry
    from agent_server.planners import get_planner

    # 装配顺序：registry 先于 planner（GraphPlanner plan() 需 registry 做 discover）
    registry = get_registry(graph=app.state.graph)

    # §20 演进：自动发现并注册 Workflows 目录（声明式 YAML → Skill）
    try:
        wf_skills = discover_workflows(
            "packages/agent-runtime/workflows",
            registry=registry,
        )
        for sk in wf_skills:
            registry.register(sk)
        logger.info("auto-registered %d workflow skills from packages/agent-runtime/workflows", len(wf_skills))
    except Exception:
        logger.warning("workflow auto-discovery failed", exc_info=True)

    app.state.registry = registry
    app.state.planner = get_planner(settings, registry=registry)
    app.state.planner_runtime = PlannerRuntime(
        registry=registry,
        llm=llm,
        mcp_manager=mcp_manager,
        pool=pool,
        max_skill_depth=settings.max_skill_depth,
        max_steps=settings.max_steps,
        max_duration_seconds=settings.max_execution_seconds or None,
        checkpoint_store=checkpoint_store,
        ownership_store=ownership_store,
    )
    # 绑定 delegate：graph 节点的 _invoke 此后经 runtime.delegate 调用
    delegate_ref.delegate = app.state.planner_runtime.delegate
    app.state.callbacks = get_langfuse_callbacks(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    logger.info(
        "agent-platform 就绪 storage=%s llm=%s pool=%s coordination=%s admission=%s revert=%s otel=%s mcp=%s planner=%s runtime_mode=%s",
        "postgres" if settings.db_enabled else "memory",
        settings.llm_enabled,
        pool is not None,
        settings.coordination_enabled,
        admission_controller is not None,
        settings.revert_enabled,
        settings.otel_effective_enabled,
        mcp_manager is not None,
        getattr(app.state.planner, "kind", "unknown"),
        settings.runtime_mode,
    )
    yield
    # Phase 2: OTel flush
    otel_force_flush()
    # Phase 2: MCP close
    mcp_mgr = getattr(app.state, "mcp_manager", None)
    if mcp_mgr is not None:
        await mcp_mgr.close_all()
    # checkpointer 复用 init_pool 的连接池（db_enabled 时 conn 即 _pool），
    # 生命周期归 close_pool() 统一管理，此处不再单独关闭连接。
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
