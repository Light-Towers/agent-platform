"""健康检查路由。"""

from agent_core.tracing import get_tracing_status
from agent_runtime.db import ping
from fastapi import APIRouter

from agent_server.config import get_settings
from agent_server.schemas import HealthResponse
from agent_server.sql.guard import detect_dialect

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from shared_schemas import HealthStatus

    settings = get_settings()
    db_ok = await ping() if settings.db_enabled else False
    status = HealthStatus.HEALTHY if (db_ok or not settings.db_enabled) else HealthStatus.DEGRADED
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
    )
