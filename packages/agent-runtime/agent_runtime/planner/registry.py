"""Planner 注册表：按 kind 注册/发现 Planner 实现（与 SkillRegistry 同构）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_runtime.planner.protocol import Planner


class PlannerRegistry:
    """Planner 注册表：register（拒绝重复）/ get / list / keys。"""

    def __init__(self) -> None:
        self._planners: dict[str, "Planner"] = {}

    def register(self, kind: str, planner: "Planner") -> None:
        if kind in self._planners:
            raise ValueError(f"Planner '{kind}' already registered")
        self._planners[kind] = planner

    def get(self, kind: str) -> "Planner":
        try:
            return self._planners[kind]
        except KeyError:
            raise KeyError(f"Planner '{kind}' not registered; available: {sorted(self._planners)}") from None

    def list(self) -> list["Planner"]:
        return list(self._planners.values())

    def keys(self) -> list[str]:
        return list(self._planners.keys())

    def __contains__(self, kind: str) -> bool:
        return kind in self._planners
