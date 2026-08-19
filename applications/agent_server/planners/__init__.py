"""app 侧 Planner 装配：``PLANNER`` env（``settings.planner``）决定使用哪个实现（默认 deterministic）。

- ``deterministic``：本模块 ``DeterministicPlanner``（决策与 graph.py 同源）；
- ``agentic``：联邦侧 ``AgenticPlanner``（lazy import——app 不静态依赖 agent_federation）。

Phase 3 统一 SSE/WS 出口后，``app.api`` 直接消费 ``get_planner()`` 返回的 Planner。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_server.config import get_settings
from agent_server.planners.deterministic import DeterministicPlanner

if TYPE_CHECKING:
    from agent_runtime.planner.protocol import Planner


def get_planner(settings=None) -> "Planner":
    """按 ``settings.planner``（PLANNER env）返回 Planner 实现。"""
    settings = settings or get_settings()
    if settings.planner == "agentic":
        from agent_federation.planners.agentic import AgenticPlanner  # noqa: PLC0415

        return AgenticPlanner()
    return DeterministicPlanner()


__all__ = ["DeterministicPlanner", "get_planner"]
