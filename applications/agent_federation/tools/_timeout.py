# -*- coding: utf-8 -*-
"""
工具超时隔离装饰器。

agent_core.tools.guarded.guarded_invoke 是 LangGraph 节点模式 ``(tool, state) -> dict``，
与 LangChain ``@tool`` 函数签名不兼容。本模块用 ``asyncio.wait_for`` + ``asyncio.to_thread``
实现等效的超时隔离 + 失败降级，工具失败返回错误信息而非拖垮主管 Agent。

用法::

    @tool
    @with_timeout(timeout=15)
    def my_tool(...) -> str:
        ...
"""

import asyncio
from functools import wraps

from api.monitor import monitor


def with_timeout(timeout: float = 30.0):
    """
    装饰器：将同步工具函数包装为异步 + 超时隔离 + 失败降级。

    - 超时 → 返回错误提示字符串（不抛异常），发 outcome=timeout
    - ValueError（护栏拦截）→ 发 outcome=guarded
    - 其他异常 → 返回错误提示字符串，发 outcome=exception
    - 正常 → 返回工具原结果（不发事件，success 由调用方或 runner 补）

    :param timeout: 超时上界（秒），默认 30s
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
                monitor.report_tool_outcome(
                    tool_name=func.__name__, outcome="timeout", error_class="TimeoutError")
                return f"工具 {func.__name__} 执行超时（{timeout}s），已隔离"
            except ValueError as e:
                monitor.report_tool_outcome(
                    tool_name=func.__name__, outcome="guarded", error_class="ValueError", detail=str(e))
                return f"工具 {func.__name__} 输入被护栏拒绝：{e}"
            except Exception as e:
                monitor.report_tool_outcome(
                    tool_name=func.__name__, outcome="exception", error_class=type(e).__name__, detail=str(e))
                return f"工具 {func.__name__} 执行失败：{type(e).__name__}: {e}"
        return wrapper
    return decorator
