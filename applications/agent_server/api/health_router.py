"""健康检查路由。"""

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
        mcp=settings.mcp_enabled,
    )
