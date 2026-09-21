"""OTel 分布式追踪 + W3C traceparent 传播封装（复用 agent_core 基础设施）。

agent_core.tracing 提供：懒导入 + no-op 降级 + 幂等 init + span 上下文管理器。
agent_core.tracing_propagation 提供：W3C traceparent 注入/提取/关联。

本模块做薄封装，为 exhibition-agent 提供统一入口；OTel SDK 缺失时全部 no-op。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from agent_core.logging import get_logger
from agent_core.tracing import (
    get_tracer,
    init_tracing,
    is_tracing_enabled,
    set_request_context,
    start_span,
)
from agent_core.tracing_propagation import (
    extract_traceparent as _extract_traceparent,
)
from agent_core.tracing_propagation import (
    get_current_traceparent as _get_current_traceparent,
)
from agent_core.tracing_propagation import (
    inject_traceparent as _inject_traceparent,
)
from agent_core.tracing_propagation import use_context as _use_context

from exhibition_agent.config import Settings

logger = get_logger(__name__)


def init_observability(settings: Settings) -> Any:
    """初始化 OTel 追踪（幂等，缺 SDK / 缺 endpoint 时 no-op 降级）。"""
    tracer = init_tracing(
        service_name=settings.otel_service_name,
        otel_endpoint=settings.otel_endpoint,
        enabled=settings.otel_enabled,
    )
    if is_tracing_enabled():
        logger.info("exhibition-agent OTel 已启用: service=%s endpoint=%s", settings.otel_service_name, settings.otel_endpoint)
    else:
        logger.info("exhibition-agent OTel no-op 模式（SDK 缺失或未配置 endpoint）")
    return tracer


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """span 上下文管理器（封装 agent_core.tracing.start_span，支持 kwargs 属性）。"""
    attr_dict = {k: v for k, v in attrs.items() if v is not None}
    with start_span(name, attr_dict if attr_dict else None) as s:
        yield s


def inject_traceparent(headers: dict[str, str]) -> dict[str, str]:
    """将当前 span context 注入 HTTP 请求头（W3C traceparent）。"""
    return _inject_traceparent(headers)


def extract_traceparent(headers: dict[str, str] | Any) -> Any:
    """从 HTTP 请求头提取 W3C traceparent，返回 OTel Context。"""
    return _extract_traceparent(headers)


def use_context(ctx: Any) -> Any:
    """将提取的 context 设为当前 span 的 parent context。"""
    return _use_context(ctx)


def get_current_traceparent() -> str | None:
    """获取当前 span 的 W3C traceparent 字符串（响应头回传用）。"""
    return _get_current_traceparent()


def get_tracer_instance() -> Any:
    """返回当前 tracer（no-op 时返回 no-op tracer）。"""
    return get_tracer()


__all__ = [
    "init_observability",
    "span",
    "inject_traceparent",
    "extract_traceparent",
    "use_context",
    "get_current_traceparent",
    "get_tracer_instance",
    "set_request_context",
]
