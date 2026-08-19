"""AgenticPlanner：联邦侧 deep_agent 自主决策执行（Plan-F Phase 2 协议适配）。

包装 ``agent_federation.agent.main_agent._execute_agent_core``（返回最终答案字符串），
使联邦 deep_agent 执行符合统一 Planner 协议：``plan(ctx) -> Plan`` + ``execute(plan, runtime) -> StreamEvent``。

边界：``run_deep_agent`` 的 guard/intent/cache/memory/monitor 副作用链路保持不动，
本类只做协议适配，供 ``PLANNER=agentic`` 时统一消费。``execute()`` 已把
``_execute_agent_core`` 运行期的 monitor 事件（assistant_call/tool_start/...）桥接为
``evidence`` StreamEvent，使 WS 流更丰富（route -> evidence* -> answer）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from agent_runtime.planner.protocol import Plan, Planner, PlannerContext, PlannerRuntime, StreamEvent

logger = logging.getLogger(__name__)

# monitor 事件 -> evidence StreamEvent 的桥接：让 WS 流携带运行时证据/记忆上下文。
# 仅桥接有信息量的事件类型，避免噪音（如纯 heartbeat）。
_MONITOR_BRIDGE_TYPES = (
    "assistant_call",   # 子 agent 调用
    "tool_start",       # 工具/能力调用
    "tool_outcome",     # 工具结果
    "session_created",  # 工作目录/记忆上下文建立
    "task_result",      # 子任务完成
    "circuit_state_change",  # 熔断器状态（可观测性）
    "error",            # 执行错误
)


def _monitor_event_to_stream_event(event: dict[str, Any]) -> StreamEvent | None:
    """把 monitor 事件负载桥接为 ``evidence`` StreamEvent。

    保持只读转换：monitor 事件原文（event/message/data）原样透传，不丢信息；
    无法识别的类型返回 ``None``（调用方跳过）。
    """
    event_type = event.get("event")
    if event_type not in _MONITOR_BRIDGE_TYPES:
        return None
    return StreamEvent(
        type="evidence",
        payload={
            "source": "federated_monitor",
            "event": event_type,
            "message": event.get("message", ""),
            "data": event.get("data", {}),
            "timestamp": event.get("timestamp"),
        },
    )


def _subscribe_monitor(handler: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
    """临时订阅全部桥接事件类型，返回注销函数（并发安全：每个 execute 用自己的闭包+列表）。"""
    from agent_core.monitor import monitor  # noqa: PLC0415

    for t in _MONITOR_BRIDGE_TYPES:
        monitor.on(t, handler)

    def _unsub() -> None:
        for t in _MONITOR_BRIDGE_TYPES:
            monitor.off(t, handler)

    return _unsub


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

        # 桥接 monitor 事件为 evidence StreamEvent，使 WS 流携带运行时证据/记忆上下文。
        # _execute_agent_core 执行期间通过全局 monitor 发射 assistant_call/tool_start/...，
        # 这里临时订阅并在 answer 前按序 yield，不改黑盒内部契约。
        events: list[StreamEvent] = []

        def _handle(ev: dict[str, Any]) -> None:
            se = _monitor_event_to_stream_event(ev)
            if se is not None:
                events.append(se)

        unsub = _subscribe_monitor(_handle)
        try:
            answer = await _execute_agent_core(question, workspace_id)
        except Exception as exc:  # noqa: BLE001
            unsub()
            logger.warning("agentic 执行异常: %s", exc)
            yield StreamEvent(type="error", payload={"error": str(exc)})
            yield StreamEvent(type="answer", payload={"text": ""})
            return
        unsub()

        for se in events:
            yield se
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
        - 经 ``runtime.execution()`` 界定单次执行预算边界 + ``runtime.skill_guard``
          包裹 ``_execute_agent_core``：将 Phase 3 组合治理
          (max_skill_depth/max_steps)落地到联邦主链路；护栏违规抛 ``SkillCompositionError``。
        - ``main_agent`` 透传：保留联邦 P5 动态 agent 选择能力（None 时 _execute_agent_core
          内部回退静态单例），不进统一 Planner 协议（属联邦内部 concern）。
        - ``_execute_agent_core`` 内部保持原样发射 monitor/assistant_call/task_result 等事件，
          联邦 guard/intent/cache/memory 副作用链在 ``run_deep_agent`` 层保留，零破坏 eval/WS 契约。
        """
        from agent_federation.agent.main_agent import _execute_agent_core  # noqa: PLC0415

        async with runtime.execution():
            async with runtime.skill_guard("agentic"):
                return await _execute_agent_core(question, workspace_id, main_agent)
