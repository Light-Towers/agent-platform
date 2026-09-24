"""warehouse REST mock server（v1.2：直接 REST 端点，9 场景）。

v1.2 不再实现 POST /api/v1/skills/{skill}；改为直接 mock warehouse REST 端点：
- GET /api/venue-schedule（venue.schedule.query skill 主端点）
- GET /api/portrait/exhibition/{exhibition_id}（展会画像）
- GET /api/health（健康检查）

按 X-Mock-Scenario 头切换场景：
1. normal_200              → 200 + REST JSON（data_readiness.level=complete + citations）
2. missing_context         → 401（ExecutionContext 头缺失，middleware 校验）
3. scope_denied            → 403（空 scopes，middleware 校验）
4. knowledge_not_published → 404 + {"error":{"code":"KNOWLEDGE_NOT_PUBLISHED"}}
5. metric_not_verified     → 422 + {"error":{"code":"METRIC_NOT_VERIFIED"}}
6. metric_blocked          → 422 + {"error":{"code":"METRIC_BLOCKED"}}
7. data_not_connected      → 200 + {"data_readiness":{"level":"pending"}}（INV-10 200 路径）
8. data_not_connected_422  → 422 + {"error":{"code":"DATA_NOT_CONNECTED"}}（INV-10 422 路径）
9. missing_readiness       → 200 + 无 data_readiness 字段（skill 层默认 READY）

mock 侧复用 exhibition-agent 的 C1 中间件校验 ExecutionContext（契约 C1 保留）。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from exhibition_agent.contract.error_codes import ErrorCode
from exhibition_agent.middleware.execution_context_middleware import (
    AuthContextInvalidError,
    AuthContextMissingError,
    ExecutionContextError,
    ScopeDeniedError,
    resolve_execution_context,
)
from exhibition_agent.observability.otel import extract_traceparent, span, use_context

MOCK_SCENARIOS: tuple[str, ...] = (
    "normal_200",
    "missing_context",
    "scope_denied",
    "knowledge_not_published",
    "metric_not_verified",
    "metric_blocked",
    "data_not_connected",
    "data_not_connected_422",
    "missing_readiness",
)


def create_mock_app() -> FastAPI:
    """创建 warehouse REST mock FastAPI app（v1.2）。"""
    app = FastAPI(title="warehouse-mock", description="跨项目接口契约 v1.2 REST 假实现")

    @app.get("/api/venue-schedule")
    async def venue_schedule(request: Request) -> JSONResponse:
        return await _handle_rest_scenario(
            request,
            skill="venue.schedule.query",
            path="/api/venue-schedule",
        )

    @app.get("/api/portrait/exhibition/{exhibition_id}")
    async def exhibition_profile(exhibition_id: str, request: Request) -> JSONResponse:
        return await _handle_rest_scenario(
            request,
            skill="exhibition.profile.query",
            path=f"/api/portrait/exhibition/{exhibition_id}",
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health_root() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _handle_rest_scenario(
    request: Request,
    *,
    skill: str,
    path: str,
) -> JSONResponse:
    """按 X-Mock-Scenario 头返回 REST 响应（复用 C1 中间件校验）。"""
    scenario = request.headers.get("X-Mock-Scenario", "normal_200")
    ctx_header = request.headers.get("X-Execution-Context")
    context_mode = request.headers.get("X-Context-Mode", "jwt")

    propagated_ctx = extract_traceparent(dict(request.headers))

    with use_context(propagated_ctx):
        with span(
            "warehouse_mock.rest_endpoint",
            request_id=ctx_header or "unknown",
            skill=skill,
            path=path,
            scenario=scenario,
        ):
            return await _dispatch_scenario(scenario, skill, path, ctx_header, context_mode, request)


async def _dispatch_scenario(
    scenario: str,
    skill: str,
    path: str,
    ctx_header: str | None,
    context_mode: str,
    request: Request,
) -> JSONResponse:
    """按场景分发响应。"""
    if scenario == "missing_context":
        return _error_response(ErrorCode.AUTH_CONTEXT_MISSING, "X-Execution-Context 头缺失")

    try:
        ctx = resolve_execution_context(
            ctx_header,
            mode=context_mode,
            path=path,
            skill=skill,
            self_reported_tenant_id=_extract_self_reported_tenant(request),
        )
    except AuthContextMissingError as exc:
        return _error_response(ErrorCode.AUTH_CONTEXT_MISSING, exc.message, 401)
    except AuthContextInvalidError as exc:
        return _error_response(ErrorCode.AUTH_CONTEXT_INVALID, exc.message, 401)
    except ScopeDeniedError as exc:
        return _error_response(ErrorCode.SCOPE_DENIED, exc.message, 403)
    except ExecutionContextError as exc:
        return _error_response(ErrorCode.INTERNAL, exc.message, exc.http_status)

    if scenario == "scope_denied":
        return _error_response(ErrorCode.SCOPE_DENIED, "越权访问该 exhibition 资源")
    if scenario == "knowledge_not_published":
        return _error_response(ErrorCode.KNOWLEDGE_NOT_PUBLISHED, "知识状态为 DRAFT，未发布")
    if scenario == "metric_not_verified":
        return _error_response(ErrorCode.METRIC_NOT_VERIFIED, "指标 sales_rate 已注册但未 VERIFIED")
    if scenario == "metric_blocked":
        return _error_response(ErrorCode.METRIC_BLOCKED, "指标 venue_occupancy 处于 BLOCKED 状态")
    if scenario == "data_not_connected_422":
        return _error_response(ErrorCode.DATA_NOT_CONNECTED, "数据源 t_venue_schedule 未接入")
    if scenario == "data_not_connected":
        return JSONResponse(
            status_code=200,
            content={
                "venue": "保利世贸博览馆",
                "data_readiness": {"level": "pending", "reason": "t_venue_schedule 未接入"},
            },
        )
    if scenario == "missing_readiness":
        return JSONResponse(
            status_code=200,
            content={
                "venue": "保利世贸博览馆",
                "exhibition": "SIAL 广州 2026",
                "date_range": "2026-09-03 ~ 2026-09-05",
            },
        )

    return _success_response(ctx.tenant_id)


def _extract_self_reported_tenant(request: Request) -> str | None:
    """从 query params 提取自报 tenant_id（C1 校验用）。"""
    return request.query_params.get("tenant_id")


def _success_response(tenant_id: str) -> JSONResponse:
    """正常 200 REST JSON（data_readiness.level=complete + citations）。"""
    return JSONResponse(
        status_code=200,
        content={
            "venue": "保利世贸博览馆",
            "exhibition": "SIAL 广州 2026",
            "date_range": "2026-09-03 ~ 2026-09-05",
            "status": "scheduled",
            "data_readiness": {"level": "complete"},
            "as_of": "2026-09-01",
            "citations": [
                {"knowledge_id": "kb-venue-sial-gz-001", "chunk_id": "c-12", "scope": f"tenant:{tenant_id}"},
            ],
        },
    )


def _error_response(
    code: ErrorCode,
    message: str,
    http_status: int | None = None,
) -> JSONResponse:
    """错误响应（v1.2：HTTP 状态码 + JSON body，不再走信封）。"""
    from exhibition_agent.contract.error_codes import ERROR_CODE_HTTP_MAP

    status = http_status or ERROR_CODE_HTTP_MAP[code]
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code.value,
                "message": message,
                "retryable": code in (ErrorCode.RATE_LIMITED, ErrorCode.UPSTREAM_ERROR),
            },
        },
    )
