# -*- coding: utf-8 -*-
"""StructuredTool 观测包装（langchain 可选隔离模块，方案 v3 批 1）。

隔离模式同 :mod:`agent_core.llm.fallback_lc`：本模块 import langchain_core，
**仅在调用方显式使用 :func:`agent_core.observability.observe_tool` 时经函数级
import 加载**；agent_core 其余内核模块不得 import 本模块（内核零依赖铁律）。

职责（单一实现，federation tool_registry / agent_server SkillRegistry 均为装配点）：
- 对 StructuredTool 的 ``func``（sync）与 ``coroutine``（async）**双路分别包装**；
- 进入时发 ``tool_start``（args 摘要，单值 repr 截断 512 字符）；
- 结束时发 ``tool_outcome``：ToolResult → 其 outcome；普通返回 → success；
  外抛 → exception（error_class=类型名）后 **re-raise**（不改变原异常语义）；
- ``duration_ms`` 一并上报（monitor 追加字段）；
- ``name`` / ``description`` / ``args_schema`` 经 ``model_copy`` 原样保留。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from langchain_core.tools import StructuredTool

from agent_core.monitor import monitor as _global_monitor
from agent_core.observability.tool_result import ToolOutcome, ToolResult

__all__ = ["observe_tool_lc"]

_DETAIL_TRUNCATE = 512


def _truncate(text: str) -> str:
    return text if len(text) <= _DETAIL_TRUNCATE else text[:_DETAIL_TRUNCATE] + "…<truncated>"


def _summarize_args(args: dict[str, Any]) -> dict[str, str]:
    """入参摘要：逐值 repr 截断（全量 args/result 全文在 Trajectory，不入事件）。"""
    return {k: _truncate(repr(v)) for k, v in (args or {}).items()}


def observe_tool_lc(
    tool: StructuredTool,
    *,
    display_names: dict[str, str] | None = None,
    monitor: Any | None = None,
) -> StructuredTool:
    """返回包装后的 StructuredTool 副本（原对象不变；事件经 monitor 上报）。

    Args:
        tool: langchain ``@tool`` 产物（StructuredTool 实例）。
        display_names: ``tool.name -> 展示名`` 映射（迁移期兼容现中文人工名）；
            未命中时用 ``tool.name`` 原名。
        monitor: 显式注入 ToolMonitor（测试隔离用）；缺省用全局共享单例。
    """
    mon = monitor if monitor is not None else _global_monitor
    display = (display_names or {}).get(tool.name, tool.name)

    def _report_start(kwargs: dict[str, Any]) -> None:
        mon.report_tool(tool_name=display, args=_summarize_args(kwargs))

    def _report_outcome(
        outcome: str | ToolOutcome,
        *,
        error_class: str | None = None,
        detail: str = "",
        duration_ms: float,
    ) -> None:
        mon.report_tool_outcome(
            tool_name=display,
            outcome=outcome.value if isinstance(outcome, ToolOutcome) else outcome,
            error_class=error_class,
            detail=_truncate(detail),
            duration_ms=duration_ms,
        )

    def _finalize(result: Any, duration_s: float) -> Any:
        duration_ms = round((time.monotonic() - duration_s) * 1000, 1)
        if isinstance(result, ToolResult):
            _report_outcome(
                result.outcome,
                error_class=result.error_class,
                detail=result.detail,
                duration_ms=duration_ms,
            )
            return result.text
        _report_outcome(ToolOutcome.SUCCESS, duration_ms=duration_ms)
        return result

    def _wrap_sync(func: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any):
            start = time.monotonic()
            _report_start(kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _report_outcome(
                    ToolOutcome.EXCEPTION,
                    error_class=type(exc).__name__,
                    detail=str(exc),
                    duration_ms=round((time.monotonic() - start) * 1000, 1),
                )
                raise
            return _finalize(result, start)

        return wrapper

    def _wrap_async(coro_func: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Any):
            start = time.monotonic()
            _report_start(kwargs)
            try:
                result = await coro_func(*args, **kwargs)
            except Exception as exc:
                _report_outcome(
                    ToolOutcome.EXCEPTION,
                    error_class=type(exc).__name__,
                    detail=str(exc),
                    duration_ms=round((time.monotonic() - start) * 1000, 1),
                )
                raise
            return _finalize(result, start)

        return wrapper

    updates: dict[str, Any] = {}
    if tool.func is not None:
        updates["func"] = _wrap_sync(tool.func)
    if tool.coroutine is not None:
        updates["coroutine"] = _wrap_async(tool.coroutine)
    if not updates:
        raise ValueError(f"observe_tool: 工具 {tool.name!r} 无 func/coroutine 可包装")

    # model_copy 保留 name/description/args_schema（pydantic 实例禁用 functools.wraps）
    return tool.model_copy(update=updates)
