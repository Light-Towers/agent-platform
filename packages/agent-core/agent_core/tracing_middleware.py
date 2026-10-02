# -*- coding: utf-8 -*-
"""纯 ASGI 请求级 tracing 中间件（kernel 单一实现，方案 §3.2，复盘 R10/R12）。

存在的理由：handler 内手写 span 只覆盖 happy path——429 admission 拒绝、
409 coordination 拒绝、cache_hit 直返、客户端断连、未捕获异常都会绕过 span
创建，恰在最需要观测的旁路路径失明（R10）。本中间件为**每个** HTTP 请求创建
一个 server span 并在 finally 恒定 end()，旁路在结构上消失；handler 内经
:func:`agent_core.tracing.record_request_attributes` 补业务属性即可覆盖全路径
（R8 的手写 span 土壤随之移除）。

设计约束：
- **纯 ASGI**：不依赖 Starlette ``BaseHTTPMiddleware``（避免流式响应被缓冲/包装），
  任何 ASGI 宿主（FastAPI/裸 Starlette/uvicorn）可直接装配；
- **请求时门控**：``is_tracing_enabled()`` 为 False 直接透传（opt-in 铁律，
  关闭态零性能损耗、绝不抛异常）；
- **W3C traceparent 入站提取为父**（R6 传播面的唯一挂载点，经
  :func:`agent_core.tracing_propagation.extract_traceparent`，读 kernel 单状态机）；
- attach/detach 在**同一 await 调用链**内配对（L-1 合规：中间件对下游是单层
  await，不存在 SSE 生成器跨任务拆分问题——那是 R8 中 handler 手动 enter/exit 的病灶）。

装配方式：经 ``agent_core.guardrails.app_factory.build_api_app(enable_tracing=True)``
统一装配（构造保证不可漏接）；lint L-3 保证 init 只在装配点。
"""

from __future__ import annotations

import contextlib
from typing import Any, Callable, MutableMapping

from agent_core.tracing import get_tracer, is_tracing_enabled
from agent_core.tracing_propagation import extract_traceparent

__Scope = MutableMapping[str, Any]
__Receive = Callable[[], Any]
__Send = Callable[[Any], Any]


class TracingMiddleware:
    """为每个 HTTP 请求创建 server span（kind=SERVER），入站 traceparent 为父。

    span 名 ``"<METHOD> <path>"``；属性：``http.method`` / ``http.target`` /
    ``http.status_code``（拦截 ``http.response.start``）；5xx 与未捕获异常置
    ERROR 状态并 record_exception；断连（CancelledError）同样落 span 后原样抛出。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: __Scope, receive: __Receive, send: __Send) -> None:
        if scope["type"] != "http" or not is_tracing_enabled():
            await self.app(scope, receive, send)
            return

        # 启用态必然有 SDK（init 成功才会 ACTIVE）；极端竞态下 import 失败则透传。
        try:
            from opentelemetry import context as otel_context
            from opentelemetry.trace import SpanKind, Status, StatusCode, set_span_in_context
        except ImportError:  # pragma: no cover - 仅状态切换竞态可达
            await self.app(scope, receive, send)
            return

        headers: dict[str, str] = {}
        for raw_key, raw_val in scope.get("headers") or ():
            with contextlib.suppress(Exception):
                headers[bytes(raw_key).decode("latin-1").lower()] = bytes(raw_val).decode("latin-1")

        # R6：入站 traceparent 提取为父上下文（未启用/缺失时为 None → 本地 root span）
        parent_ctx = extract_traceparent(headers)
        method = str(scope.get("method", "HTTP"))
        path = str(scope.get("path", ""))

        tracer = get_tracer()
        span = tracer.start_span(
            f"{method} {path}",
            context=parent_ctx,
            kind=SpanKind.SERVER,
            attributes={"http.method": method, "http.target": path},
        )
        token = otel_context.attach(set_span_in_context(span))

        async def _send_wrapped(message: Any) -> None:
            if message.get("type") == "http.response.start":
                status = message.get("status")
                with contextlib.suppress(Exception):  # 观测不得影响响应链路
                    span.set_attribute("http.status_code", status)
                    if isinstance(status, int) and status >= 500:
                        span.set_status(Status(StatusCode.ERROR))
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapped)
        except BaseException as exc:  # 含 asyncio.CancelledError（客户端断连，R10 覆盖面）
            with contextlib.suppress(Exception):
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise
        finally:
            with contextlib.suppress(Exception):
                otel_context.detach(token)
            span.end()


__all__ = ["TracingMiddleware"]
