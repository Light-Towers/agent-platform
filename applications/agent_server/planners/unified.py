"""UnifiedPlanner（Phase A 收口）：按 Mode Selector 结果逐请求分发到具体 Planner。

保持 ``Planner`` 协议（plan/execute），对上游（``app.api`` / ``app.state.planner``）透明：
- ``plan()``：先经 ModeSelector 选范式，再委托对应子 Planner 产出 Plan；范式写入
  ``plan.notes["execution_mode"]``；
- ``execute()``：按范式分发执行（workflow 复用 ``execute_plan`` 的统一 Runtime 路径，
  其余委托对应子 Planner 的 execute）。

``settings.planner == "auto"`` 时启用自动选择；其余值由 ModeSelector 作为强制 override。
默认 ``deterministic``，自动选择为 opt-in（doc §16 Phase A：保留 ``PLANNER=`` 作为 override）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from agent_runtime.planner.execution_graph import execute_plan
from agent_runtime.planner.mode_selector import ExecutionMode, ModeSelector
from agent_runtime.planner.protocol import (
    ExecutionContext,
    Plan,
    Planner,
    PlannerContext,
    PlannerRuntime,
    StreamEvent,
)

if TYPE_CHECKING:
    from agent_runtime.skills.registry import SkillRegistry

    from agent_server.config import Settings


class UnifiedPlanner(Planner):
    """逐请求 Mode Selector 分发：自动选择或强制 override。"""

    kind = "unified"

    def __init__(
        self,
        settings: "Settings",
        registry: "SkillRegistry | None" = None,
        *,
        selector: "ModeSelector | None" = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        force = None if settings.planner == "auto" else settings.planner
        self._selector = selector or ModeSelector(force_mode=force)

    async def plan(self, ctx: PlannerContext) -> Plan:
        decision = await self._selector.select(ctx, self._registry)
        sub = self._sub_planner(decision.mode)
        plan = await sub.plan(ctx)
        plan.execution_mode = decision.mode.value
        if decision.mode == ExecutionMode.WORKFLOW and decision.workflow_skill:
            # workflow 模式：复用 Workflow Skill（已注册）作为单 route 能力
            plan = Plan(
                mode="workflow",
                route=decision.workflow_skill,
                sub_query=ctx.question,
                reason=f"Mode Selector → Workflow Skill {decision.workflow_skill}",
                execution_mode=ExecutionMode.WORKFLOW.value,
            )
        return plan

    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        mode = getattr(plan, "execution_mode", None) or plan.mode
        if mode == ExecutionMode.WORKFLOW.value or plan.mode == "workflow":
            # workflow 经 execute_plan 的单一 route 分支走统一 Runtime（受治理 + 轨迹持久化）
            async for event in execute_plan(plan, runtime):
                yield event
            return
        sub = self._sub_planner(ExecutionMode(mode))
        async for event in sub.execute(plan, runtime, ctx):
            yield event

    def _sub_planner(self, mode: ExecutionMode) -> Planner:
        if mode == ExecutionMode.GRAPH:
            from agent_server.planners.graph import GraphPlanner

            return GraphPlanner(registry=self._registry)
        if mode == ExecutionMode.AGENTIC:
            from agent_federation.planners.agentic import AgenticPlanner

            return AgenticPlanner()
        return _DeterministicOrWorkflowPlanDelegate(self._settings)


class _DeterministicOrWorkflowPlanDelegate(Planner):
    """deterministic 路径：直接复用 DeterministicPlanner（含路由/记忆/合成/重规划）。"""

    kind = "deterministic"

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    async def plan(self, ctx: PlannerContext) -> Plan:
        from agent_server.planners.deterministic import DeterministicPlanner

        return await DeterministicPlanner().plan(ctx)

    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        from agent_server.planners.deterministic import DeterministicPlanner

        async for event in DeterministicPlanner().execute(plan, runtime, ctx):
            yield event


__all__ = ["UnifiedPlanner"]
