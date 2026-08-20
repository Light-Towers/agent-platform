"""GraphPlanner：组合型 Planner — discover 候选 Skill → 构建 ExecutionGraph → execute_plan。

Plan-F 执行链打通：Planner 产出带 ``ExecutionGraph`` 的 Plan，经 ``PolicyValidator`` 校验 +
``execute_graph`` 分层并行执行。与 ``DeterministicPlanner``（单 route）和 ``AgenticPlanner``
（LLM 自主 function-calling）并行，经 ``PLANNER=graph`` env 选择。

当前为基础版：``plan()`` 用 ``discover`` 选 Top-1 候选 Skill 构建单节点 ExecutionGraph。
完整版应经 LLM 决策多 Skill 组合（依赖关系 / 并行），但基础版已验证
``Plan → PolicyValidator → execute_graph`` 主链打通。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from agent_runtime.planner.execution_graph import execute_plan
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


class GraphPlanner(Planner):
    """组合型 Planner：产出 ExecutionGraph，经 execute_plan 执行。

    - ``plan()``：``discover`` 候选 Skill → 构建 ExecutionGraph → ``Plan(mode="graph")``
    - ``execute()``：``plan.graph`` 非空时走 ``execute_plan``（validate → execute_graph）
    """

    kind = "graph"

    def __init__(self, registry: "SkillRegistry | None" = None) -> None:
        self._registry = registry

    async def plan(self, ctx: PlannerContext) -> Plan:
        registry = self._registry
        if registry is None:
            return Plan(
                mode="deterministic",
                route="direct",
                reason="GraphPlanner 无 registry，回退 deterministic",
                notes={"question": ctx.question},
            )

        candidates = registry.discover(ctx.question, top_k=10)
        if not candidates:
            return Plan(
                mode="deterministic",
                route="direct",
                reason="无候选 Skill，回退 direct",
                notes={"question": ctx.question},
            )

        # 基础版：选 Top-1 候选构建单节点 ExecutionGraph
        # 完整版：LLM 决策多 Skill 组合（依赖/并行），构建多节点 DAG
        skill = candidates[0]
        from agent_runtime.planner.execution_graph import ExecutionGraph

        g = ExecutionGraph()
        g.add_node("n0", skill.name, {"query": ctx.question})

        return Plan(
            mode="graph",
            route="graph",
            sub_query=ctx.question,
            reason=f"经 discover 选中 {skill.name}",
            graph=g,
            notes={
                "question": ctx.question,
                "workspace_id": ctx.workspace_id,
                "user_id": ctx.user_id,
            },
        )

    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if plan.graph is not None:
            async for event in execute_plan(plan, runtime):
                yield event
        else:
            yield StreamEvent(
                type="route", payload={"capability": plan.route, "reason": plan.reason}
            )
            yield StreamEvent(type="answer", payload={"text": ""})
