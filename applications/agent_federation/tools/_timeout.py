# -*- coding: utf-8 -*-
"""
工具超时隔离装饰器。

agent_core.tools.guarded.guarded_invoke 是 LangGraph 节点模式 ``(tool, state) -> dict``，
与 LangChain ``@tool`` 函数签名不兼容。本模块用 ``asyncio.wait_for`` + ``asyncio.to_thread``
实现等效的超时隔离 + 失败降级，工具失败返回错误信息而非拖垮主管 Agent。

用法::

    @tool
    @with_timeout(timeout=15)
    def my_tool(...) -> str | ToolResult:
        ...

批 2 改造（方案 v3.1 定板）：三分支返回 ``ToolResult``（outcome 语义承载唯一
方案），事件上报统一由 ``agent_core.observability.observe_tool`` 包装器派生——
本模块不再直调 monitor。包装器把 ToolResult.text 转发给 LLM 链路，
ToolResult.outcome 进 tool_outcome 事件；observe_tool 未接线时降级为
str(ToolResult) = text（行为兼容）。
"""

import asyncio
from functools import wraps

from agent_core.observability import ToolOutcome, ToolResult


def with_timeout(timeout: float = 30.0):
    """
    装饰器：将同步工具函数包装为异步 + 超时隔离 + 失败降级。

    - 超时 → 返回 ToolResult(outcome=timeout, text=提示)（不抛异常）
    - ValueError（护栏拦截）→ 返回 ToolResult(outcome=guarded)
    - 其他异常 → 返回 ToolResult(outcome=exception)
    - 正常 → 返回工具原结果（success 由包装器派生）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return ToolResult(
                    text=f"工具 {func.__name__} 执行超时（{timeout}s），已隔离",
                    outcome=ToolOutcome.TIMEOUT,
                    error_class="TimeoutError",
                )
            except ValueError as e:
                return ToolResult(
                    text=f"工具 {func.__name__} 输入被护栏拒绝：{e}",
                    outcome=ToolOutcome.GUARDED,
                    error_class="ValueError",
                    detail=str(e),
                )
            except Exception as e:
                return ToolResult(
                    text=f"工具 {func.__name__} 执行失败：{type(e).__name__}: {e}",
                    outcome=ToolOutcome.EXCEPTION,
                    error_class=type(e).__name__,
                    detail=str(e),
                )
        return wrapper
    return decorator
