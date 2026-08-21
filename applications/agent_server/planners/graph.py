"""GraphPlanner：组合型 Planner — discover 候选 Skill → LLM 组合 ExecutionGraph → execute_plan。

Plan-F 执行链打通（Phase B 升级）：
- 单候选 / 无 LLM：退化为单节点 ExecutionGraph（基础版，兼容旧行为）；
- 多候选 + LLM：经 ``compose_execution_graph`` 产出多 Skill DAG（含输入映射与依赖边），
  组合失败时按 doc §16 Phase B 重新规划（有限次重试 + 错误反馈），而非进入无限 Agent loop；
  仍失败时回退单节点能力，保证可治理、可审计。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from agent_runtime.planner.execution_graph import ExecutionGraph, execute_plan
from agent_runtime.planner.graph_compose import (
    GraphComposeError,
    compose_execution_graph,
)
from agent_runtime.planner.policy import PlanViolationError
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
    """组合型 Planner：产出 ExecutionGraph，经 execute_plan 执行（validate → execute_graph）。"""

    kind = "graph"

    def __init__(
        self,
        registry: "SkillRegistry | None" = None,
        *,
        max_compose_retries: int = 1,
        max_execution_replans: int = 1,
    ) -> None:
        self._registry = registry
        self._max_compose_retries = max_compose_retries
        self._max_execution_replans = max_execution_replans

    def _single_node_plan(self, ctx: PlannerContext, skill_name: str, reason: str) -> Plan:
        g = ExecutionGraph()
        g.add_node("n0", skill_name, {"query": ctx.question})
        return Plan(
            mode="graph",
            route="graph",
            sub_query=ctx.question,
            reason=reason,
            graph=g,
            notes={
                "question": ctx.question,
                "workspace_id": ctx.workspace_id,
                "user_id": ctx.user_id,
                "last_snapshot": ctx.last_snapshot,
            },
        )

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

        # 单候选或无 LLM：基础版单节点（兼容旧行为，避免无意义组合）
        if ctx.llm is None or len(candidates) < 2:
            return self._single_node_plan(
                ctx, candidates[0].name, f"单候选，选 {candidates[0].name}"
            )

        # 多候选 + LLM：组合多 Skill DAG（带错误反馈重规划）
        graph = await self._compose_with_retry(ctx, candidates)
        if graph is None:
            return self._single_node_plan(
                ctx, candidates[0].name, "LLM 组合失败，回退单节点"
            )
        return Plan(
            mode="graph",
            route="graph",
            sub_query=ctx.question,
            reason="LLM 组合多 Skill DAG",
            graph=graph,
            notes={
                "question": ctx.question,
                "workspace_id": ctx.workspace_id,
                "user_id": ctx.user_id,
                "last_snapshot": ctx.last_snapshot,
            },
        )

    async def _compose_with_retry(
        self, ctx: PlannerContext, candidates: list
    ) -> "ExecutionGraph | None":
        feedback: str | None = None
        for _ in range(self._max_compose_retries + 1):
            try:
                return await compose_execution_graph(
                    ctx.question, candidates, ctx.llm, feedback=feedback
                )
            except GraphComposeError as exc:
                feedback = f"上一次规划非法：{exc}。请修正后重新产出合法 DAG。"
        return None

    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if plan.graph is None:
            yield StreamEvent(
                type="route", payload={"capability": plan.route, "reason": plan.reason}
            )
            yield StreamEvent(type="answer", payload={"text": ""})
            return

        plan_ctx = PlannerContext(
            question=plan.sub_query or plan.notes.get("question", ""),
            workspace_id=plan.notes.get("workspace_id", "default"),
            user_id=plan.notes.get("user_id", "default"),
            llm=runtime.llm,
            last_snapshot=plan.notes.get("last_snapshot"),
        )
        # 执行期重规划：PolicyValidator 拒绝（非法图）时，有限次重新规划而非无限 loop
        for attempt in range(self._max_execution_replans + 1):
            try:
                async for event in execute_plan(plan, runtime):
                    yield event
                return
            except PlanViolationError as exc:
                if attempt >= self._max_execution_replans or self._registry is None:
                    yield StreamEvent(
                        type="error",
                        payload={"error": f"执行图策略校验失败且重规划无效: {exc}"},
                    )
                    return
                replanned = await self.plan(plan_ctx)
                if replanned.graph is None:
                    yield StreamEvent(
                        type="error",
                        payload={"error": f"重规划未能产出合法图: {exc}"},
                    )
                    return
                plan = replanned
                yield StreamEvent(
                    type="replan",
                    payload={
                        "iteration": attempt + 1,
                        "to_route": "graph",
                        "reason": f"policy_violation: {exc}",
                    },
                )


__all__ = ["GraphPlanner"]
