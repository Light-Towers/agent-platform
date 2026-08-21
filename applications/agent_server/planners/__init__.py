"""app 侧 Planner 装配：``PLANNER`` env（``settings.planner``）决定使用哪个实现（默认 deterministic）。

- ``deterministic``：本模块 ``DeterministicPlanner``（决策与 graph.py 同源）；
- ``graph``：本模块 ``GraphPlanner``（discover → ExecutionGraph → execute_plan，组合治理主链）；
- ``agentic``：联邦侧 ``AgenticPlanner``（lazy import——app 不静态依赖 agent_federation）。

Phase 3 统一 SSE/WS 出口后，``app.api`` 直接消费 ``get_planner()`` 返回的 Planner。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_server.config import get_settings
from agent_server.planners.deterministic import DeterministicPlanner

if TYPE_CHECKING:
    from agent_runtime.planner.protocol import Planner
    from agent_runtime.skills.registry import SkillRegistry


def get_planner(settings=None, *, registry: "SkillRegistry | None" = None) -> "Planner":
    """按 ``settings.planner``（PLANNER env）返回 Planner 实现。

    - ``auto``：启用 Phase A Mode Selector（UnifiedPlanner 逐请求自动选择范式）；
    - ``deterministic``（默认）/ ``graph`` / ``agentic``：强制对应实现（override，doc §16）。

    ``registry``：GraphPlanner / Mode Selector 需要（plan() 经 discover 选候选 Skill）。
    """
    settings = settings or get_settings()
    if settings.planner == "auto":
        from agent_server.planners.unified import UnifiedPlanner  # noqa: PLC0415

        return UnifiedPlanner(settings, registry=registry)
    if settings.planner == "agentic":
        from agent_federation.planners.agentic import AgenticPlanner  # noqa: PLC0415

        return AgenticPlanner()
    if settings.planner == "graph":
        from agent_server.planners.graph import GraphPlanner  # noqa: PLC0415

        return GraphPlanner(registry=registry)
    return DeterministicPlanner()


__all__ = [
    "DeterministicPlanner",
    "GraphPlanner",
    "UnifiedPlanner",
    "get_planner",
]
