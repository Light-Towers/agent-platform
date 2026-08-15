"""W3C traceparent 跨服务上下文传播。

方案 Phase 0 实现要点：
  "跨服务 trace 传播用 W3C traceparent（httpx 请求头注入，子服务提取并关联 span），
   否则联邦架构下'全链路'名不副实"

本模块基于 OpenTelemetry 标准 propagation 机制（W3C TraceContext 格式）：
  - 网关侧：调子服务前 inject_traceparent(headers) 注入 traceparent 到请求头
  - 子服务侧：收到请求后 extract_traceparent(headers) 提取并关联到当前 span

无 OTel SDK 或未启用时自动 no-op（与 agent-core tracing 降级策略一致）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_otel_propagate: Any = None
_propagation_available: bool = False
try:
    from opentelemetry import propagate as _otel_propagate  # noqa: PLC0415

    _propagation_available = True
except Exception:  # pragma: no cover - OTel 未安装
    _propagation_available = False


def inject_traceparent(headers: dict[str, str]) -> dict[str, str]:
    """将当前 span context 注入到 HTTP 请求头（W3C traceparent）。

    网关侧调用子服务前使用：
        headers = {"Authorization": f"Bearer {key}"}
        headers = inject_traceparent(headers)
        resp = await client.post(url, headers=headers, ...)

    无 OTel / 未启用时 no-op，原样返回 headers。

    Args:
        headers: 原始请求头字典

    Returns:
        注入 traceparent 后的请求头（原地修改并返回）
    """
    if not _propagation_available:
        return headers
    try:
        from agent_core.tracing import is_tracing_enabled

        if not is_tracing_enabled():
            return headers
    except Exception:
        return headers

    try:
        _otel_propagate.inject(headers)
        if "traceparent" in headers:
            logger.debug("traceparent 已注入: %s", headers["traceparent"][:32])
    except Exception as e:  # noqa: BLE001
        logger.debug("traceparent 注入失败（非致命）: %s", e)
    return headers


def extract_traceparent(headers: Mapping[str, str]) -> Any:
    """从 HTTP 请求头提取 W3C traceparent，返回 OTel Context。

    子服务侧收到请求时使用：
        ctx = extract_traceparent(request.headers)
        with use_context(ctx):
            # 此 span 自动关联到网关侧的 trace

    无 OTel / 未启用时返回 None（调用方应走默认 context）。

    Args:
        headers: HTTP 请求头（Mapping，如 FastAPI Request.headers）

    Returns:
        OTel Context 对象，或 None（未启用/提取失败）
    """
    if not _propagation_available:
        return None
    try:
        from agent_core.tracing import is_tracing_enabled

        if not is_tracing_enabled():
            return None
    except Exception:
        return None

    try:
        ctx = _otel_propagate.extract(dict(headers))
        if ctx is not None:
            logger.debug("traceparent 已提取")
        return ctx
    except Exception as e:  # noqa: BLE001
        logger.debug("traceparent 提取失败（非致命）: %s", e)
        return None


def use_context(ctx: Any):
    """将提取的 context 设为当前 span 的 parent context。

    子服务侧用法：
        ctx = extract_traceparent(headers)
        with use_context(ctx):
            with start_span("subservice.handle"):
                ...

    无 ctx 时返回 nullcontext（不改变当前 context）。

    Args:
        ctx: extract_traceparent 返回的 OTel Context

    Returns:
        上下文管理器（with 语句使用）
    """
    from contextlib import nullcontext

    if ctx is None or not _propagation_available:
        return nullcontext()

    try:
        from opentelemetry.context import attach, detach

        token = attach(ctx)

        class _DetachCM:
            def __enter__(self):
                return self

            def __exit__(self, *exc: Any) -> bool:
                detach(token)
                return False

        return _DetachCM()
    except Exception as e:  # noqa: BLE001
        logger.debug("use_context 失败（非致命）: %s", e)
        return nullcontext()


def get_current_traceparent() -> str | None:
    """获取当前 span 的 W3C traceparent 字符串（用于日志/调试/响应回传）。

    Returns:
        traceparent 字符串，或 None（未启用/无当前 span）
    """
    if not _propagation_available:
        return None
    try:
        from agent_core.tracing import is_tracing_enabled

        if not is_tracing_enabled():
            return None
    except Exception:
        return None

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return None
        ctx = span.get_span_context()
        if ctx is None or not ctx.is_valid:
            return None
        return f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{int(ctx.trace_flags):02x}"
    except Exception:
        return None
