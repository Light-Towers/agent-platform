# -*- coding: utf-8 -*-
"""
入站安全护栏 ASGI 中间件（框架无关内核，源自 zhiku M5 security_guards）。

按请求顺序执行：
1. 生成请求级 request_id 并注入 OTel 上下文（与 tracing 打通）；
2. 载荷大小护栏（Content-Length 超限 → 413，最廉价 DoS 防护）；
3. API Key 鉴权（配置了 api_key 非空才启用；缺失/不匹配 → 401，``secrets.compare_digest`` 防时序攻击）；
4. 入站限流（按 client 优先 X-API-Key 其次 IP 的滑动窗口 + 全局窗口；超限 429 + Retry-After）。

设计要点：
- 纯 ASGI 中间件（不用 BaseHTTPMiddleware），避免对 /stream SSE 流式响应产生缓冲干扰；
- 鉴权关闭语义：api_key 为空 → 跳过鉴权，限流与载荷护栏照常生效；
- 框架无关：``app.api.errors.error_response`` 改为**可注入回调** ``error_response``，
  starlette 为可选依赖（web extra），``app.core.tracing`` 改为 ``agent_core.tracing``。

需要 starlette（``web`` extra）；导入本模块前请先安装 starlette。
"""

import secrets
from typing import Any, Callable, Optional, Tuple

from starlette.requests import Request

from agent_core.guardrails.auth import (
    DEFAULT_EXEMPT_PATHS,
    extract_api_key_from_headers,
    resolve_client_key,
    should_skip_all_guards,
    should_skip_auth,
    should_skip_rate_limit,
)
from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter
from agent_core.logging import get_logger
from agent_core.tracing import generate_request_id, set_request_context

logger = get_logger(__name__)

# error_response 回调签名：(status_code, code, msg, request_id, headers=None) -> ASGI Response
ErrorResponseFactory = Callable[..., Any]


def _default_error_response(
    status_code: int,
    code: str,
    msg: str,
    request_id: str,
    headers: Optional[dict] = None,
) -> Any:
    """内置默认错误响应（基于 starlette JSONResponse），供未注入 error_response 时使用。"""
    from starlette.responses import JSONResponse

    resp_headers = dict(headers or {})
    if request_id and "X-Trace-Id" not in resp_headers:
        resp_headers["X-Trace-Id"] = request_id
    return JSONResponse(status_code=status_code, content={"code": code, "msg": msg, "request_id": request_id}, headers=resp_headers)


class SecurityGuardsMiddleware:
    """入站安全护栏中间件（鉴权 + 限流 + 载荷大小 + request_id 注入）。"""

    def __init__(
        self,
        app: Any,
        api_key: str = "",
        rate_limit_per_client: int = 20,
        rate_limit_global: int = 500,
        rate_limit_window_s: int = 60,
        max_body_bytes: int = 65536,
        exempt_paths: Tuple[str, ...] = DEFAULT_EXEMPT_PATHS,
        per_client_limiter: Optional[SlidingWindowRateLimiter] = None,
        global_limiter: Optional[SlidingWindowRateLimiter] = None,
        error_response: Optional[ErrorResponseFactory] = None,
    ) -> None:
        self.app = app
        self.api_key = api_key or ""
        self.rate_limit_per_client = max(1, rate_limit_per_client)
        self.rate_limit_global = max(1, rate_limit_global)
        self.rate_limit_window_s = max(1, rate_limit_window_s)
        self.max_body_bytes = max(1, max_body_bytes)
        self.exempt_paths = exempt_paths or DEFAULT_EXEMPT_PATHS
        self._per_client = per_client_limiter or SlidingWindowRateLimiter(
            self.rate_limit_per_client, self.rate_limit_window_s
        )
        self._global = global_limiter or SlidingWindowRateLimiter(self.rate_limit_global, self.rate_limit_window_s)
        # error_response 可注入（宿主应用传入自己的统一错误构造器）；缺省用内置 starlette 实现。
        self._error_response: ErrorResponseFactory = error_response or _default_error_response

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path
        method = request.method

        # 1) 请求级 request_id（OTel 打通）：middleware 在路由/根 span 之前执行，
        #    先注入上下文，保证后续 401/429/400 也带 X-Trace-Id 与 request_id 可追踪。
        request_id = generate_request_id()
        set_request_context(request_id=request_id)
        request.state.request_id = request_id

        # CORS 预检兜底：OPTIONS 直接放行
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        skip_all = should_skip_all_guards(path, self.exempt_paths)

        # 2) 载荷大小护栏（最廉价 DoS：超大请求体直接拒绝，不进入解析）
        if not skip_all:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > self.max_body_bytes:
                        await self._reject(
                            scope,
                            send,
                            request_id,
                            413,
                            "PAYLOAD_TOO_LARGE",
                            f"请求体过大（上限 {self.max_body_bytes} 字节）",
                        )
                        return
                except ValueError:
                    pass  # 非法 Content-Length 交由后续解析 / 异常处理器兜底

        # 3) API Key 鉴权（配置了 key 才启用）
        if self.api_key and not should_skip_auth(path, self.exempt_paths):
            provided = extract_api_key_from_headers(request.headers)
            if not provided or not secrets.compare_digest(provided, self.api_key):
                logger.warning("Unauthorized access %s %s from %s", method, path, self._client_ip(request))
                await self._reject(
                    scope,
                    send,
                    request_id,
                    401,
                    "UNAUTHORIZED",
                    "无效的 API Key，请检查 X-API-Key 或 Authorization: Bearer 请求头",
                )
                return

        # 4) 入站限流（按 client + 全局）
        if not should_skip_rate_limit(path, self.exempt_paths):
            client_key = resolve_client_key(request.headers, self._client_ip(request), bool(self.api_key))
            allowed, retry_after = self._per_client.allow(client_key)
            if not allowed:
                logger.warning("Rate limited client %s %s %s", method, path, client_key)
                await self._reject(
                    scope,
                    send,
                    request_id,
                    429,
                    "RATE_LIMITED",
                    f"请求过于频繁，请稍后重试（{self.rate_limit_per_client} 次/{self.rate_limit_window_s} 秒）",
                    headers={"Retry-After": str(retry_after)},
                )
                return
            allowed_global, retry_after_global = self._global.allow("__global__")
            if not allowed_global:
                logger.warning("Global rate limited %s %s", method, path)
                await self._reject(
                    scope,
                    send,
                    request_id,
                    429,
                    "RATE_LIMITED",
                    "服务繁忙，请稍后重试（全局限流）",
                    headers={"Retry-After": str(retry_after_global)},
                )
                return

        # 5) 放行：为所有响应注入 X-Trace-Id
        await self.app(scope, receive, self._wrap_send(send, request_id))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else ""

    @staticmethod
    def _wrap_send(send: Any, request_id: str) -> Any:
        """包装 send：给 http.response.start 统一注入 X-Trace-Id 头。"""

        async def _send_with_trace(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"x-trace-id" for k, _ in headers):
                    headers.append((b"x-trace-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        return _send_with_trace

    async def _reject(
        self,
        scope: Any,
        send: Any,
        request_id: str,
        status_code: int,
        code: str,
        msg: str,
        headers: Optional[dict] = None,
    ) -> None:
        """直接返回统一错误响应（不进入路由）。"""
        response = self._error_response(status_code, code, msg, request_id, headers=headers)
        await response(scope, None, send)


__all__ = ["SecurityGuardsMiddleware", "DEFAULT_EXEMPT_PATHS", "_default_error_response"]
