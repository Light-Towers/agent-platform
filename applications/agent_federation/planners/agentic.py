"""agent_federation 的 agentic 执行器工厂（F-S1-02 收口）。

AgenticPlanner 类已迁至 ``agent_runtime.planner.agentic``（消除 agent_server →
agent_federation 直接 import）。本模块提供执行器工厂并在 import 时自动注册。

执行器：``_execute_agent_core``（联邦 deep_agent 全链路执行，含
guard/intent/cache/memory/monitor 副作用链）。
"""

from __future__ import annotations

from collections.abc import Callable

from agent_runtime.planner.agentic import AgenticPlanner, register_agentic_executor_factory


def get_executor_factory() -> Callable:
    """返回 agentic 执行器函数（``_execute_agent_core``）。

    每次调用都重新 import，使 monkeypatch 能生效（测试场景）。
    """
    from agent_federation.agent.main_agent import _execute_agent_core  # noqa: PLC0415

    return _execute_agent_core


register_agentic_executor_factory(get_executor_factory)


__all__ = ["AgenticPlanner", "get_executor_factory"]
