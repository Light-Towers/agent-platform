"""AgenticPlanner：通用 agentic 执行适配器（Plan-F F-S1-02 收口）。

从 ``agent_federation/planners/agentic.py`` 迁入 agent-runtime，消除
agent_server → agent_federation 的直接 import（红线 2）。

执行器（``_execute_agent_core``）通过 entry_points 发现：
agent_federation 在其 pyproject.toml 中声明 ``agent_runtime.agentic_executor``
entry point，本模块经 ``importlib.metadata`` 发现并加载——agent_runtime 不 import
任何 application，agent_server 也不 import agent_federation。

显式注册（``register_agentic_executor_factory``）供测试和手动接入使用。
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from agent_runtime.planner.protocol import (
    ExecutionContext,
    Plan,
    Planner,
    PlannerContext,
    PlannerRuntime,
    SkillCompositionError,
    StreamEvent,
)
from agent_runtime.skills.registry import Skill, SkillKind

logger = logging.getLogger(__name__)

_MONITOR_BRIDGE_TYPES = (
    "assistant_call",
    "tool_start",
    "tool_outcome",
    "session_created",
    "task_result",
    "circuit_state_change",
    "error",
)

_EXECUTOR_EP_GROUP = "agent_runtime.agentic_executor"
_executor_factory: Callable[[], Callable] | None = None


def register_agentic_executor_factory(factory: Callable[[], Callable]) -> None:
    """显式注册 agentic 执行器工厂（供测试 / 手动接入）。

    优先级高于 entry_points；调用后覆盖任何已发现的工厂。
    """
    global _executor_factory
    _executor_factory = factory


def _discover_executor_factory() -> Callable[[], Callable]:
    global _executor_factory
    if _executor_factory is not None:
        return _executor_factory
    try:
        eps = importlib.metadata.entry_points(group=_EXECUTOR_EP_GROUP)
        for ep in eps:
            _executor_factory = ep.load()
            return _executor_factory
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "发现 agentic 执行器 entry point 失败。"
            "若未安装 agent-federation-app，运行 `uv sync --extra agentic`。"
        ) from exc
    raise RuntimeError(
        "未找到 agentic 执行器。安装 agent-federation-app：`uv sync --extra agentic`，"
        "或显式调用 register_agentic_executor_factory()。"
    )


def _monitor_event_to_stream_event(event: dict[str, Any]) -> StreamEvent | None:
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
    from agent_core.monitor import monitor  # noqa: PLC0415

    for t in _MONITOR_BRIDGE_TYPES:
        monitor.on(t, handler)

    def _unsub() -> None:
        for t in _MONITOR_BRIDGE_TYPES:
            monitor.off(t, handler)

    return _unsub


class AgenticPlanner(Planner):
    """Agentic Planner：不显式路由，交给 LLM agent 自主决策。

    执行器经 entry_points 发现（或显式注册），本类不直接 import 任何 application。
    """

    kind = "agentic"

    async def plan(self, ctx: PlannerContext) -> Plan:
        return Plan(
            route="agentic",
            sub_query=ctx.question,
            reason="agentic planner 自主决策（deep_agent）",
            question=ctx.question,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user_id,
        )

    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        factory = _discover_executor_factory()
        executor = factory()

        question = plan.question or plan.sub_query or ""
        workspace_id = plan.workspace_id

        yield StreamEvent(type="route", payload={"capability": "agentic", "reason": plan.reason})

        events: list[StreamEvent] = []

        def _handle(ev: dict[str, Any]) -> None:
            se = _monitor_event_to_stream_event(ev)
            if se is not None:
                events.append(se)

        unsub = _subscribe_monitor(_handle)
        try:
            async with runtime.execution():
                async with runtime.skill_guard("agentic"):
                    answer = await executor(question, workspace_id)
        except SkillCompositionError:
            unsub()
            raise
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
        factory = _discover_executor_factory()
        executor = factory()

        async with runtime.execution():
            async with runtime.skill_guard("agentic"):
                return await executor(question, workspace_id, main_agent)

    def to_skill(
        self,
        *,
        timeout_ms: int | None = None,
        permissions: frozenset[str] | set[str] | None = None,
    ) -> Skill:
        """将 AgenticPlanner 包装为 SkillKind.AGENT 型 Skill。

        executor 经 entry_points 发现（或显式注册），接受 ``question`` / ``workspace_id`` kwargs。
        注册到 SkillRegistry 后可经 ``runtime.delegate("agentic", question=..., workspace_id=...)`` 调用，
        也可在 ExecutionGraph 中作为节点引用。

        :raises RuntimeError: entry_points 不可用且未显式注册执行器时。
        """
        factory = _discover_executor_factory()

        async def execute(**kwargs: Any) -> Any:
            executor = factory()
            question = kwargs.get("question", "")
            workspace_id = kwargs.get("workspace_id", "default")
            main_agent = kwargs.get("main_agent")
            if main_agent is not None:
                return await executor(question, workspace_id, main_agent)
            return await executor(question, workspace_id)

        return Skill(
            name="agentic",
            description="Agentic Planner：LLM agent 自主决策（deep_agent）",
            kind=SkillKind.AGENT,
            executor=execute,
            timeout_ms=timeout_ms,
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "workspace_id": {"type": "string"},
                },
                "required": ["question"],
            },
            permissions=frozenset(permissions) if permissions else frozenset(),
        )


__all__ = [
    "AgenticPlanner",
    "register_agentic_executor_factory",
]
