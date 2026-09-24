# -*- coding: utf-8 -*-
"""入站统一错误信封 / 异常处理器（P2，全局优先，方案 §3.1）。

从 ``knowledge_service.utils.error_response_utils`` 上提到 kernel，供全仓共享，
与 ``agent_core.guardrails.web``（SecurityGuardsMiddleware）同属**入站横切层**——
错误处理是这一层的另一面。

分层：
- 纯逻辑（``ERROR_CODES`` / ``error_code_for_status`` / ``error_body``）零第三方依赖，
  仅装 stdlib 的 venv 也能 import、可独立单测；
- ``make_error_response`` / ``install_error_handlers`` 需要的 starlette 为**函数内懒导入**
  （``web`` extra），保持本模块可无 starlette 导入。

D-2=A：``install_error_handlers`` 仅注册 ``Exception → 500`` 兜底脱敏，
**不改**各 app 现有 4xx ``HTTPException`` 的 ``{detail}`` 对外信封（零破坏）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from agent_core.logging import get_logger

# 未捕获异常对外统一脱敏文案（详情仅入服务端日志，不外泄堆栈/内部路径/密钥）。
SANITIZED_5XX_MSG = "服务器内部错误，请稍后重试"

# 状态码 → 机器可读错误码（对外稳定，便于客户端程序化处理；不泄露内部细节）。
ERROR_CODES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    422: "UNPROCESSABLE_ENTITY",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def error_code_for_status(status_code: int) -> str:
    """状态码 → 对外错误码；未登记的状态码退回通用 HTTP_ERROR。"""
    return ERROR_CODES.get(status_code, "HTTP_ERROR")


def error_body(code: str, msg: str, request_id: str) -> Dict[str, Any]:
    """构造统一错误响应体 {code, msg, request_id}。"""
    return {"code": code, "msg": msg, "request_id": request_id or ""}


def _default_get_request_id() -> str:
    """缺省 request_id 来源：agent-core OTel 上下文（懒导入，避免硬依赖）。"""
    from agent_core.tracing import get_request_id

    return get_request_id()


def make_error_response(
    status_code: int,
    code: str,
    msg: str,
    request_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """构造统一错误 JSONResponse（自动带 X-Trace-Id 头）。需 starlette（``web`` extra）。"""
    from starlette.responses import JSONResponse

    resp_headers = dict(headers or {})
    if request_id and "X-Trace-Id" not in resp_headers:
        resp_headers["X-Trace-Id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, msg, request_id),
        headers=resp_headers,
    )


def install_error_handlers(
    app: Any,
    *,
    get_request_id: Optional[Callable[[], str]] = None,
    logger: Optional[Any] = None,
    sanitize_5xx_msg: str = SANITIZED_5XX_MSG,
) -> Any:
    """注册未捕获异常 → 500 脱敏 handler（D-2=A：仅 ``Exception``，不动 4xx 信封）。

    - ``get_request_id`` / ``logger`` 注入：解耦各应用日志与 trace 实现；
      缺省分别用 ``agent_core.tracing.get_request_id`` 与 ``agent_core.logging``。
    - agent-core **不 import applications**（红线 1），仅依赖 starlette 处理器注册。
    - 优先读中间件写入的 ``request.state.request_id``（与 401/429/400 共用同一 trace），
      无中间件时回退 OTel 上下文。
    """
    rid = get_request_id or _default_get_request_id
    log = logger or get_logger("agent_core.guardrails.errors")

    async def unhandled_exception_handler(request: Any, exc: Exception) -> Any:
        request_id = getattr(request.state, "request_id", "") or rid()
        log.exception("Unhandled exception %s %s", request.method, request.url.path)
        return make_error_response(500, "INTERNAL_ERROR", sanitize_5xx_msg, request_id)

    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


__all__ = [
    "SANITIZED_5XX_MSG",
    "ERROR_CODES",
    "error_code_for_status",
    "error_body",
    "make_error_response",
    "install_error_handlers",
]
