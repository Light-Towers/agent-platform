"""FastAPI server：nl2sql-service API 入口。"""

from agent_core.guardrails.app_factory import build_api_app
from agent_core.tracing import init_tracing
from agent_runtime.identity_assembly import mount_identity_gate
from fastapi import FastAPI, Request
from shared_schemas import HealthResponse, HealthStatus

from nl2sql_service.api.dependencies import lifespan
from nl2sql_service.api.routers.pools_router import router as pools_router
from nl2sql_service.api.routers.query_router import router


async def handle_health(http_request: Request) -> HealthResponse:
    return HealthResponse(status=HealthStatus.HEALTHY, version="0.1.0", dependencies=[])


def create_app() -> FastAPI:
    # 观测装配点（roadmap 阶段2 #12）：默认关闭，无 endpoint 即 no-op（不抛异常）。
    # 放在 create_app 而非 lifespan：lifespan 里会构造模型/连接，OTel provider 是
    # 进程级全局单例，必须先于它们装配（同 agent_server/main.py 的顺序约束）。
    init_tracing(service_name="nl2sql-service")
    app = build_api_app(title="nl2sql-service", version="0.1.0", lifespan=lifespan)
    # 身份门卫装配点（roadmap 阶段2 #11）：本服务此前**零门卫且零租户维度**——契约里有
    # ``tenant_id`` 字段但源码从不读它。默认 observe 档只建立服务端断言上下文，不改响应；
    # 真正的「按断言隔离数据」需要先定义本服务的租户作用域（见方案 §5.2，待拍板）。
    mount_identity_gate(app, "nl2sql-service")
    app.include_router(router)
    app.include_router(pools_router)
    app.get("/health", response_model=HealthResponse)(handle_health)
    return app


app = create_app()
