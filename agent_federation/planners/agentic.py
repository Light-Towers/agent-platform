"""AgenticPlanner：联邦侧 deep_agent 自主决策执行（Plan-F Phase 2 协议适配）。

包装 ``agent_federation.agent.main_agent._execute_agent_core``（返回最终答案字符串），
使联邦 deep_agent 执行符合统一 Planner 协议：``plan(ctx) -> Plan`` + ``execute(plan, runtime) -> StreamEvent``。

边界：``run_deep_agent`` 的 guard/intent/cache/memory/monitor 副作用链路保持不动，
本类只做协议适配，供 ``PLANNER=agentic`` 时统一消费（Phase 3 统一 SSE 出口时再整合全链路）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from agent_runtime.planner.protocol import Plan, Planner, PlannerContext, PlannerRuntime, StreamEvent

logger = logging.getLogger(__name__)


class AgenticPlanner(Planner):
    """Agentic Planner：不显式路由，交给 LLM agent 自主决策（deep_agent 全链路执行）。"""

    kind = "agentic"

    async def plan(self, ctx: PlannerContext) -> Plan:
        return Plan(
            route="agentic",
            sub_query=ctx.question,
            reason="agentic planner 自主决策（deep_agent）",
            notes={"question": ctx.question, "workspace_id": ctx.workspace_id, "user_id": ctx.user_id},
        )

    async def execute(self, plan: Plan, runtime: PlannerRuntime) -> AsyncIterator[StreamEvent]:
        # lazy import：避免模块顶层拉起 main_agent 全局副作用
        from agent_federation.agent.main_agent import _execute_agent_core  # noqa: PLC0415

        question = plan.notes.get("question") or plan.sub_query or ""
        workspace_id = plan.notes.get("workspace_id", "default")

        yield StreamEvent(type="route", payload={"capability": "agentic", "reason": plan.reason})
        try:
            answer = await _execute_agent_core(question, workspace_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agentic 执行异常: %s", exc)
            yield StreamEvent(type="error", payload={"error": str(exc)})
            yield StreamEvent(type="answer", payload={"text": ""})
            return
        yield StreamEvent(type="answer", payload={"text": answer})

    async def arun(
        self,
        question: str,
        workspace_id: str,
        runtime: PlannerRuntime,
        main_agent: Any = None,
    ) -> str:
        """联邦侧执行入口（供 ``run_deep_agent`` 复用）：返回答案字符串，并套组合治理护栏。

        - 与 ``execute``(供 app SSE)并存：``execute`` 产出 StreamEvent 流，本方法返回字符串。
        - 经 ``runtime.skill_guard`` 包裹 ``_execute_agent_core``：将 Phase 3 组合治理
          (max_skill_depth/max_steps)落地到联邦主链路；护栏违规抛 ``SkillCompositionError``。
        - ``main_agent`` 透传：保留联邦 P5 动态 agent 选择能力（None 时 _execute_agent_core
          内部回退静态单例），不进统一 Planner 协议（属联邦内部 concern）。
        - ``_execute_agent_core`` 内部保持原样发射 monitor/assistant_call/task_result 等事件，
          联邦 guard/intent/cache/memory 副作用链在 ``run_deep_agent`` 层保留，零破坏 eval/WS 契约。
        """
        from agent_federation.agent.main_agent import _execute_agent_core  # noqa: PLC0415

        async with runtime.skill_guard("agentic"):
            return await _execute_agent_core(question, workspace_id, main_agent)
