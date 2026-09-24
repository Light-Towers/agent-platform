"""FastAPI server：nl2sql-service API 入口。"""

from agent_core.guardrails.app_factory import build_api_app
from fastapi import FastAPI, Request
from shared_schemas import HealthResponse, HealthStatus

from nl2sql_service.api.dependencies import lifespan
from nl2sql_service.api.routers.query_router import router


async def handle_health(http_request: Request) -> HealthResponse:
    return HealthResponse(status=HealthStatus.HEALTHY, version="0.1.0", dependencies=[])


def create_app() -> FastAPI:
    app = build_api_app(title="nl2sql-service", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.get("/health", response_model=HealthResponse)(handle_health)
    return app


app = create_app()
