"""warehouse 契约 mock server（9 场景）。

模拟 warehouse `/api/v1/skills/{skill}` 端点，按 X-Mock-Scenario 头切换场景：
1. normal_200              → 成功信封（readiness/classification/sources/citations 齐全）
2. missing_context         → 401 AUTH_CONTEXT_MISSING（头缺失）
3. scope_denied            → 403 SCOPE_DENIED
4. knowledge_not_published → 404 KNOWLEDGE_NOT_PUBLISHED
5. metric_not_verified     → 422 METRIC_NOT_VERIFIED
6. metric_blocked          → 422 METRIC_BLOCKED
7. data_not_connected      → 422 DATA_NOT_CONNECTED
8. knowledge_missing_citations → 200 成功但缺 citations（GroundednessError 用例）
9. missing_readiness       → 成功响应但缺 readiness（客户端判 fail 用例）

mock 侧也用 exhibition-agent 的 C1 中间件校验 ExecutionContext（复用契约定义）。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from exhibition_agent.contract.error_codes import ERROR_CODE_HTTP_MAP, ErrorCode
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
    "knowledge_missing_citations",
    "missing_readiness",
)


def create_mock_app() -> FastAPI:
    """创建 warehouse mock FastAPI app。"""
    app = FastAPI(title="warehouse-mock", description="跨项目接口契约 v1.1 假实现")

    @app.post("/api/v1/skills/{skill}")
    async def skill_endpoint(skill: str, request: Request) -> JSONResponse:
        scenario = request.headers.get("X-Mock-Scenario", "normal_200")
        ctx_header = request.headers.get("X-Execution-Context")
        context_mode = request.headers.get("X-Context-Mode", "jwt")

        body: dict[str, Any] = await request.json()
        request_id = body.get("request_id", "unknown")

        propagated_ctx = extract_traceparent(dict(request.headers))

        with use_context(propagated_ctx):
            with span(
                "warehouse_mock.skill_endpoint",
                request_id=request_id,
                skill=skill,
                scenario=scenario,
            ):
                return await _handle_scenario(
                    scenario, skill, ctx_header, context_mode, body, request_id
                )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _handle_scenario(
    scenario: str,
    skill: str,
    ctx_header: str | None,
    context_mode: str,
    body: dict[str, Any],
    request_id: str,
) -> JSONResponse:
    """按场景返回响应（从 skill_endpoint 抽出，便于 span 包裹）。"""
    if scenario == "missing_context":
        return _error_response(request_id, ErrorCode.AUTH_CONTEXT_MISSING, "X-Execution-Context 头缺失")

    try:
        ctx = resolve_execution_context(
            ctx_header,
            mode=context_mode,
            path=f"/api/v1/skills/{skill}",
            skill=skill,
            self_reported_tenant_id=body.get("params", {}).get("tenant_id"),
        )
    except AuthContextMissingError as exc:
        return _error_response(request_id, ErrorCode.AUTH_CONTEXT_MISSING, exc.message, 401)
    except AuthContextInvalidError as exc:
        return _error_response(request_id, ErrorCode.AUTH_CONTEXT_INVALID, exc.message, 401)
    except ScopeDeniedError as exc:
        return _error_response(request_id, ErrorCode.SCOPE_DENIED, exc.message, 403)
    except ExecutionContextError as exc:
        return _error_response(request_id, ErrorCode.INTERNAL, exc.message, exc.http_status)

    if scenario == "scope_denied":
        return _error_response(request_id, ErrorCode.SCOPE_DENIED, "越权访问该 exhibition 资源")
    if scenario == "knowledge_not_published":
        return _error_response(request_id, ErrorCode.KNOWLEDGE_NOT_PUBLISHED, "知识状态为 DRAFT，未发布")
    if scenario == "metric_not_verified":
        return _error_response(request_id, ErrorCode.METRIC_NOT_VERIFIED, "指标 sales_rate 已注册但未 VERIFIED")
    if scenario == "metric_blocked":
        return _error_response(request_id, ErrorCode.METRIC_BLOCKED, "指标 venue_occupancy 处于 BLOCKED 状态")
    if scenario == "data_not_connected":
        return _error_response(request_id, ErrorCode.DATA_NOT_CONNECTED, "数据源 t_venue_schedule 未接入")
    if scenario == "knowledge_missing_citations":
        return JSONResponse(
            status_code=200,
            content={
                "request_id": request_id,
                "data": {"summary": "某搭建规范摘要"},
                "readiness": "READY",
                "classification": "INTERNAL",
                "sources": [{"type": "knowledge", "name": "kb-build-spec-001"}],
                "citations": [],
                "warnings": [],
            },
        )
    if scenario == "missing_readiness":
        return JSONResponse(
            status_code=200,
            content={
                "request_id": request_id,
                "data": {"occupancy": 0.78},
                "classification": "INTERNAL",
                "sources": [{"type": "table", "name": "t_venue_schedule", "as_of": "2026-09-01"}],
            },
        )

    return _success_response(request_id, ctx.tenant_id)


def _success_response(request_id: str, tenant_id: str) -> JSONResponse:
    """正常 200 成功信封（readiness/classification/sources/citations 齐全）。"""
    return JSONResponse(
        status_code=200,
        content={
            "request_id": request_id,
            "data": {
                "venue": "保利世贸博览馆",
                "exhibition": "SIAL 广州 2026",
                "date_range": "2026-09-03 ~ 2026-09-05",
                "status": "scheduled",
            },
            "readiness": "READY",
            "classification": "INTERNAL",
            "sources": [
                {"type": "table", "name": "t_venue_schedule", "as_of": "2026-09-01"},
            ],
            "citations": [
                {"knowledge_id": "kb-venue-sial-gz-001", "chunk_id": "c-12", "scope": f"tenant:{tenant_id}"},
            ],
            "warnings": [],
        },
    )


def _error_response(
    request_id: str,
    code: ErrorCode,
    message: str,
    http_status: int | None = None,
) -> JSONResponse:
    """错误信封。"""
    status = http_status or ERROR_CODE_HTTP_MAP[code]
    return JSONResponse(
        status_code=status,
        content={
            "request_id": request_id,
            "error": {"code": code.value, "message": message, "retryable": code in (ErrorCode.RATE_LIMITED, ErrorCode.UPSTREAM_ERROR)},
        },
    )
