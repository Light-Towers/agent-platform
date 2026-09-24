"""exhibition-agent FastAPI demo 入口（含统一 Web 控制台）。

端点：
    GET  /                  → Web 控制台（static/index.html）
    POST /api/encode-context → 把 ExecutionContext JSON 编码成 X-Execution-Context 头值
    POST /api/query         → 查询（运行 Supervisor 图，返回 answer + readiness + citations）
    GET  /health            → 健康检查

启动：
    uvicorn exhibition_agent.server:app --port 9000
    # 配合 mock warehouse（端口 9100）：
    uvicorn exhibition_agent.mock_server.warehouse_mock:create_mock_app --port 9100
    # 浏览器打开 http://localhost:9000
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_core.guardrails.app_factory import build_api_app
from agent_core.logging import get_logger
from fastapi import Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.config import Settings
from exhibition_agent.contract.error_codes import ERROR_CODE_HTTP_MAP, PENDING_ANSWER_CODES, ErrorCode
from exhibition_agent.contract.execution_context import ExecutionContext
from exhibition_agent.graph.supervisor import run_supervisor
from exhibition_agent.middleware.context_codec import encode_base64, encode_jwt
from exhibition_agent.middleware.execution_context_middleware import (
    AuthContextInvalidError,
    AuthContextMissingError,
    RequestContextBrokenError,
    ScopeDeniedError,
    resolve_execution_context,
)
from exhibition_agent.observability.llm_obs import get_llm_obs_backend
from exhibition_agent.observability.metrics import get_default_registry
from exhibition_agent.observability.otel import (
    get_current_traceparent,
    init_observability,
    set_request_context,
    span,
)
from exhibition_agent.observability.trace import InMemoryTraceRecorder

logger = get_logger(__name__)

settings = Settings()
app = build_api_app(title="exhibition-agent", version="0.1.0")
_trace_recorder = InMemoryTraceRecorder()
_metrics_registry = get_default_registry()
_llm_obs_backend = get_llm_obs_backend(settings.llm_obs_backend)

init_observability(settings)

_STATIC_DIR = Path(__file__).parent / "static"


class QueryBody(BaseModel):
    query: str = Field(description="用户查询文本")
    params: dict[str, Any] = Field(default_factory=dict)


@app.get("/")
async def index() -> FileResponse:
    """Web 控制台首页。"""
    return FileResponse(_STATIC_DIR / "index.html")


@app.post("/api/encode-context")
async def encode_context(request: Request) -> JSONResponse:
    """把 ExecutionContext JSON 编码成 X-Execution-Context 头值。

    **安全**：STRICT 档禁用（返回 403），仅 DEV 档可用——
    生产环境由 IAM/网关负责编码，平台不暴露编码能力。

    请求体：ExecutionContext 字段（user_id / tenant_id / tenant_type / roles / scopes / auth_source / request_id）
    返回：{header, mode} —— 前端把 header 放入 X-Execution-Context 头调 /api/query
    """
    if settings.verify_signature:
        raise HTTPException(status_code=403, detail="STRICT 档禁用 encode-context 端点，由 IAM/网关负责编码")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败：{exc}") from exc

    try:
        ctx = ExecutionContext.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"ExecutionContext 校验失败：{exc}") from exc

    mode = settings.context_mode
    ctx_dict = ctx.model_dump(mode="json")
    if mode == "jwt":
        header = encode_jwt(ctx_dict, secret=settings.context_jwt_secret)
    else:
        header = encode_base64(ctx_dict)

    return JSONResponse(content={"header": header, "mode": mode})


@app.post("/api/query")
async def query(
    body: QueryBody,
    request: Request,
    x_execution_context: str | None = Header(default=None, alias="X-Execution-Context"),
    x_mock_scenario: str | None = Header(default=None, alias="X-Mock-Scenario"),
) -> JSONResponse:
    """查询：解析上下文 → 运行 Supervisor 图 → 返回 answer + readiness + citations。

    解析模式只由服务端配置 settings.context_mode 决定，不接受客户端头控制
    （防 STRICT 档 base64 绕过验签，INV-8）。
    """
    ctx_header = x_execution_context
    resolve_mode = settings.context_mode
    try:
        ctx = resolve_execution_context(
            ctx_header,
            mode=resolve_mode,
            path=str(request.url.path),
            skill="venue.schedule.query",
            self_reported_tenant_id=body.params.get("tenant_id"),
            jwt_secret=settings.context_jwt_secret,
            verify_signature=settings.verify_signature,
        )
    except AuthContextMissingError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": exc.message}) from exc
    except AuthContextInvalidError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": exc.message}) from exc
    except ScopeDeniedError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": exc.message}) from exc
    except RequestContextBrokenError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc

    query_hash = hashlib.sha256(body.query.encode("utf-8")).hexdigest()[:16]
    set_request_context(request_id=ctx.request_id, user_query_hash=query_hash)

    extra_headers: dict[str, str] = {}
    # X-Mock-Scenario 仅 DEV 档透传（审核建议 5）：STRICT 生产档忽略该头，
    # 防客户端用 mock 头切换上游行为
    if x_mock_scenario and not settings.verify_signature:
        extra_headers["X-Mock-Scenario"] = x_mock_scenario

    client = WarehouseClient(
        base_url=settings.warehouse_base_url,
        timeout=settings.warehouse_timeout,
    )

    initial_state: dict[str, Any] = {
        "query": body.query,
        "params": body.params,
        "execution_context": ctx,
        "execution_context_header": ctx_header,
        "context_mode": resolve_mode,
        "warehouse_client": client,
        "trace_recorder": _trace_recorder,
        "metrics_registry": _metrics_registry,
        "sql_statements": [],
        "extra_headers": extra_headers,
    }

    tp: str | None = None
    try:
        with span(
            "exhibition_agent.request",
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            # W4 脱敏：span 属性不得含用户查询明文，只放稳定哈希（与 otel.py
            # "数据脱敏（不含问题全文）"约定一致）
            query_hash=query_hash,
        ):
            final_state = await run_supervisor(
                initial_state,
                callbacks=_llm_obs_backend.get_callbacks() or None,
            )
            # traceparent 必须在 span 内获取（span 退出后当前 context 已失效）
            tp = get_current_traceparent()
    except Exception as exc:
        # 审核安全修复（N2）：异常串（可能含栈信息）不得直出终端用户，
        # 固定文案 + request_id 供日志关联定位
        logger.exception("supervisor 执行失败（request_id=%s）：%s", ctx.request_id, exc)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL", "message": "supervisor 执行失败", "request_id": ctx.request_id},
        ) from exc

    result = final_state.get("skill_result")
    answer = final_state.get("answer", "")
    sql_statements: list[str] = final_state.get("sql_statements", [])
    error_code = final_state.get("error")

    # traceparent 响应头对所有 JSON 响应统一附加（含 502/429 故障路径，审核建议 4：
    # 故障路径不得断 C4 trace 链路），计算上移到分支之前。
    response_headers: dict[str, str] = {}
    if tp:
        response_headers["traceparent"] = tp

    # skill 级错误 → 按契约 §C2 HTTP 映射返回（W3 完整修复，2026-09-21 二审）。
    # 注意：skill 对 ScopeDeniedError / EgressDeniedError / KnowledgeNotPublishedError /
    # GroundednessError / ReadinessMissingError 是 **return** 带 error_code 的 SkillResult
    # （非 raise），故映射条件不得加 "result is None" 前置——否则这些 403/404/500
    # 仍会落回 200。唯一例外：契约 §2.6 的"待接入"答案白名单（METRIC_NOT_VERIFIED /
    # METRIC_BLOCKED / DATA_NOT_CONNECTED）保持 200 业务响应语义。
    # retryable 语义仅保留给 429/502。
    _RETRYABLE_HTTP_STATUS: dict[str, int] = {"UPSTREAM_ERROR": 502, "RATE_LIMITED": 429}
    _PENDING_CODES: set[str] = {c.value for c in PENDING_ANSWER_CODES}
    _mapped_status: int | None = None
    if error_code:
        try:
            _mapped_status = ERROR_CODE_HTTP_MAP.get(ErrorCode(error_code))
        except ValueError:
            _mapped_status = None
    if _mapped_status is not None and error_code not in _PENDING_CODES:
        return JSONResponse(
            status_code=_mapped_status,
            content={
                "request_id": ctx.request_id,
                "answer": answer,
                "readiness": result.readiness.value if result else "NOT_CONNECTED",
                "classification": result.classification.value if result else "INTERNAL",
                "citations": [c.model_dump() for c in result.citations] if result else [],
                "sources": [s.model_dump() for s in result.sources] if result else [],
                "warnings": result.warnings if result else [],
                "error_code": error_code,
                "retryable": error_code in _RETRYABLE_HTTP_STATUS,
                "sql_statements": sql_statements,
            },
            headers=response_headers,
        )

    return JSONResponse(
        content={
            "request_id": ctx.request_id,
            "answer": answer,
            "readiness": result.readiness.value if result else "NOT_CONNECTED",
            "classification": result.classification.value if result else "INTERNAL",
            "citations": [c.model_dump() for c in result.citations] if result else [],
            "sources": [s.model_dump() for s in result.sources] if result else [],
            "warnings": result.warnings if result else [],
            "error_code": error_code,
            "sql_statements": sql_statements,
        },
        headers=response_headers,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "traces": str(len(_trace_recorder.traces))}
