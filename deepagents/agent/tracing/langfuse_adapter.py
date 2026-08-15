"""Langfuse 适配层（v4 生产级范式）：与 agent-core OTel bridge 共存。

v4 要点（langfuse>=4.0.0，当前 4.14.3）：
  - 客户端用 `get_client()` 单例（Langfuse() 多次实例化时单例复用、新参数被忽略）
  - `@observe()` 装饰器仍在 v4，用法不变；也可用 `start_as_current_observation()` 上下文管理器
  - Trace 由 OTel root span 自动定义；client.trace() 已在 v4 移除
  - 异步缓冲，进程退出前必须 `flush()` / `shutdown()`，否则丢数据

三态设计（方案 Phase 0）：
  - 开发期：LANGFUSE_PUBLIC_KEY/SECRET_KEY 未设 → no-op，零开销
  - CI/preview：Langfuse 自部署（docker-compose）→ @observe() 追踪 LLM 调用
  - 生产：Langfuse + ClickHouse → 全链路 trace + eval

与 agent-core tracing 的关系：
  - agent-core `start_span` → OTel span → OTLP exporter → Langfuse（OTel bridge，需
    AGENT_CORE_TRACE_ENABLED=true 才真实导出；compose 已配）
  - 本模块 `@observe()` → Langfuse SDK 原生追踪（LLM 调用、嵌套 span）
  - 两者共存：OTel bridge 负责非 LLM span（api.task, agent.run, tool.*），
    Langfuse SDK 负责 LLM 调用 + eval + prompt mgmt
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_langfuse_available: bool | None = None
_langfuse_client: Any = None


def _resolve_client() -> Any | None:
    """返回 v4 单例客户端；未配置/无 SDK 时返回 None。

    使用 get_client()（v4 推荐），自动读取 LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST 环境变量。
    """
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "")
    if not (public_key and secret_key and host):
        return None
    try:
        from langfuse import get_client  # noqa: PLC0415

        _langfuse_client = get_client()
        return _langfuse_client
    except ImportError:
        return None


def _check_langfuse() -> bool:
    global _langfuse_available
    if _langfuse_available is not None:
        return _langfuse_available
    _langfuse_available = _resolve_client() is not None
    return _langfuse_available


def init_langfuse() -> bool:
    """初始化 Langfuse SDK（v4 get_client 单例）。无 SDK 或无 key 时 no-op，返回 False。"""
    return _check_langfuse()


def langfuse_observe(
    name: str | None = None,
    *,
    as_type: str | None = None,
    **observe_kwargs: Any,
) -> Callable[[F], F]:
    """Langfuse @observe() 装饰器的安全包装（v4 兼容）。

    无 Langfuse SDK / 无 key 时返回原函数（no-op 降级）。
    有 Langfuse 时委托到 langfuse.observe()。

    Args:
        name: span 名称，默认用被装饰函数名
        as_type: Langfuse observation 类型（如 "generation", "span", "trace"）
        **observe_kwargs: 透传给 langfuse.observe() 的额外参数
    """

    def decorator(func: F) -> F:
        if not _check_langfuse():
            return func

        from langfuse import observe as _lf_observe  # noqa: PLC0415

        kwargs: dict[str, Any] = dict(observe_kwargs)
        if name is not None:
            kwargs["name"] = name
        if as_type is not None:
            kwargs["as_type"] = as_type
        return _lf_observe(**kwargs)(func)  # type: ignore[return-value]

    return decorator


def flush_langfuse() -> None:
    """异步 flush Langfuse 队列。进程退出前调用。"""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception:
            pass


def shutdown_langfuse() -> None:
    """刷写并终止后台线程（v4 推荐的服务退出钩子）。"""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception:
            pass
        try:
            _langfuse_client.shutdown()
        except Exception:
            pass


def is_langfuse_enabled() -> bool:
    """Langfuse 是否已启用（SDK 可用 + key 已配）。"""
    return _check_langfuse()
