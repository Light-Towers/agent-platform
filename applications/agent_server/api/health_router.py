"""健康检查路由。"""

from agent_core.tracing import get_tracing_status
from agent_runtime.db import ping
from agent_runtime.identity import resolve_startup_tenant_mode
from fastapi import APIRouter, Request

from agent_server.config import get_settings
from agent_server.schemas import HealthResponse
from agent_server.sql.guard import detect_dialect

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    from shared_schemas import HealthStatus

    settings = get_settings()
    db_ok = await ping() if settings.db_enabled else False
    status = HealthStatus.HEALTHY if (db_ok or not settings.db_enabled) else HealthStatus.DEGRADED
    state = request.app.state
    # R11 同源做法：报运行态真值，不报配置意愿值。scheduler/control_plane/cost_governance
    # 只在对应开关下才被 lifespan 装配（main.py），以「装配与否」为准而非 settings 复述。
    planner_runtime = getattr(state, "planner_runtime", None)
    # 语义检索类型名由 lifespan 启动期预热后存进 state；此处只读已存值。
    # **不得在这里调 resolve_provider()/get_embedder()**：LocalEmbedder.__init__ 是同步
    # SentenceTransformer(model)，而集群 readiness/liveness 探针 timeoutSeconds 为 1、
    # liveness 连错 3 次即杀容器 —— 在探针路径加载模型等于自己再造一次
    # 「探针连错三次 → 被 SIGKILL」。预热失败时这里降级为 unknown，仍是一条真值。
    embedding_backend = getattr(state, "embedding_backend", None) or "unknown"
    return HealthResponse(
        status=status,
        version="0.1.0",
        storage="postgres" if settings.db_enabled else "memory",
        llm=settings.llm_enabled,
        search=bool(settings.search_api_key),
        sql_backend=detect_dialect(settings.sql_dsn) if settings.sql_dsn else "none",
        coordination=settings.coordination_enabled,
        admission=settings.admission_effective_enabled,
        revert=settings.revert_enabled,
        otel=settings.otel_effective_enabled,
        # R11：报 kernel 状态机真值（ACTIVE/DEGRADED/DISABLED/UNINITIALIZED），
        # 不读 settings 意愿值；DEGRADED 真因进启动日志（get_tracing_status.reason）。
        otel_status=get_tracing_status()["status"],
        mcp=settings.mcp_enabled,
        scheduler=getattr(state, "scheduler", None) is not None,
        control_plane=getattr(state, "control_plane", None) is not None,
        cost_governance=getattr(state, "cost_governance", None) is not None,
        forensic=getattr(planner_runtime, "trajectory_store", None) is not None,
        embedding_backend=embedding_backend,
        embedding_real=bool(getattr(state, "embedding_real", False)),
        planner=settings.planner,
        guard_enabled=settings.guard_enabled,
        # Langfuse：与 embedding_backend/embedding_real 同一套"启动期算一次、这里只读已存值"。
        # enabled=意愿（三键非空），ready=运行态（回调真挂上了）；两者的差值就是故障信号。
        langfuse_enabled=bool(getattr(state, "langfuse_enabled", False)),
        langfuse_ready=bool(getattr(state, "langfuse_ready", False)),
        auth_enabled=bool(settings.api_key),
        # 与 lifespan 的 require_identity_startup_guard 同一个函数，不另建一套判定。
        identity_mode=resolve_startup_tenant_mode()[0],
    )
