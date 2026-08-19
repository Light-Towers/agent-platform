"""FastAPI server：wenda-data-agent API 入口。"""

from fastapi import FastAPI, Request
from shared_schemas import HealthResponse, HealthStatus

from wenda_data_agent.api.dependencies import lifespan
from wenda_data_agent.api.routers.query_router import router


async def handle_health(http_request: Request) -> HealthResponse:
    return HealthResponse(status=HealthStatus.HEALTHY, version="0.1.0", dependencies=[])


def create_app() -> FastAPI:
    app = FastAPI(title="wenda-data-agent", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.get("/health", response_model=HealthResponse)(handle_health)
    return app


app = create_app()
