"""FastAPI server：nl2sql-service API 入口。"""

import asyncio
from typing import Any

from agent_core.guardrails.app_factory import build_api_app
from agent_core.tracing import init_tracing
from agent_runtime.identity_assembly import mount_identity_gate
from fastapi import FastAPI, HTTPException, Request
from shared_schemas import HealthResponse, HealthStatus

from nl2sql_service.api.dependencies import lifespan
from nl2sql_service.api.routers.ingest_router import router as ingest_router
from nl2sql_service.api.routers.meta_admin_router import router as meta_admin_router
from nl2sql_service.api.routers.pools_router import router as pools_router
from nl2sql_service.api.routers.query_router import router

#: /ready 探池：取连接 + SELECT 1 的总超时（秒）。dw 池的语句超时是 30s，
#: 就绪探针等不了那么久——短超时快速失败，让 k8s 把流量切走。
_READY_PROBE_TIMEOUT_S = 3.0
#: lifespan 登记在 app.state.pools 的池名（见 api/dependencies.py 的 registry）
_READY_POOLS = ("meta", "dw")


async def handle_health(http_request: Request) -> HealthResponse:
    return HealthResponse(status=HealthStatus.HEALTHY, version="0.1.0", dependencies=[])


async def _probe_pool(pool: Any) -> None:
    """SELECT 1 探活；任何失败都抛给调用方转 503。"""

    async def _run() -> None:
        async with pool.connection(timeout=_READY_PROBE_TIMEOUT_S) as conn:
            await conn.execute("SELECT 1")

    await asyncio.wait_for(_run(), timeout=_READY_PROBE_TIMEOUT_S)


async def handle_ready(http_request: Request) -> dict:
    """GET /ready：meta/dw 两池探活（Q26① 落地方案）。

    - 健康 200；任一池缺失或 SELECT 1 失败 → 503（k8s readinessProbe 用）。
    - **不碰 /health**：那是共享 `HealthResponse` 契约，
      `test_identity_gate_assembly` 把 `dependencies == []` 钉死了；池状态
      单独开只读端点，契约零影响（同 pools_router 的理由）。
    - 池缺失（DSN 未配置或 lifespan 未跑）按不可用处理：没有 dw 池的实例
      本来就答不了查询，放行流量只会得到无解释的失败。
    """
    registry: dict = getattr(http_request.app.state, "pools", None) or {}
    failed: dict[str, str] = {}
    for name in _READY_POOLS:
        pool = registry.get(name)
        if pool is None:
            failed[name] = "pool not registered"
            continue
        try:
            await _probe_pool(pool)
        except Exception as exc:  # noqa: BLE001 - 探活必须兜住一切驱动异常
            failed[name] = type(exc).__name__
    if failed:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "pools": failed})
    return {"status": "healthy", "pools": {name: "ok" for name in _READY_POOLS}}


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
    app.include_router(meta_admin_router)
    app.include_router(ingest_router)
    app.get("/health", response_model=HealthResponse)(handle_health)
    app.get("/ready")(handle_ready)
    return app


def main() -> None:
    """console script `nl2sql-service` 入口（Q26②）。

    此前 `[project.scripts]` 指向空壳构建 CLI，装完包按命令名启动得到空转
    脚本；构建 CLI 仍走 `python -m nl2sql_service.scripts.build_meta_knowledge`。
    host/port 取 Settings（与 uvicorn 手工启动同一配置面）。
    """
    import uvicorn

    from nl2sql_service.conf.settings import get_settings

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)


app = create_app()
