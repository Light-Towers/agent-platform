"""Agentic Runtime 收口桥（完整架构 Phase D）：让 Agent loop 共享统一 Skill Runtime。

架构契约（docs/complete-agent-runtime-architecture.md §13 / §18 #4）：
- Agent 可以动态产生下一步动作，Graph 可以预先确定全部动作，**两者共享同一能力层和治理层**；
- Agentic 的 tool/subagent 调用最终应通过统一 ``SkillRegistry`` / ``Runtime`` 边界，
  **不能绕过**（否则 Policy / Budget / Trace / Retry / Audit 重新散落）。

本模块是「框架无关」的桥，deepagents / LangGraph / 其他编排框架的 agent loop 只需消费：
- ``discover_agent_tools``：把 SkillRegistry 的候选能力转为 LLM 工具列表
  （tool discovery → SkillRegistry，替代把全量能力/任意代码塞给 LLM）；
- ``RuntimeToolCaller``：agent 的 tool call 经 ``runtime.delegate`` 进入统一 Runtime
  （统一预算 / 权限 / 超时 / 熔断 / 追踪 / 轨迹），且仅允许调用已注册能力
  （拒绝任意执行器，避免第二套执行治理体系）；
- ``as_agent_skill``（skills/agent.py）：把 subagent 注册为 Agent Skill，
  使「subagent 作为 Agent Skill」同样经统一 Runtime 执行。

具体的 deepagents 接入（把本桥注入其 tool loop）属于联邦侧集成步骤。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.planner.protocol import PlannerRuntime
from agent_runtime.skills.registry import SkillNotFoundError, SkillRegistry


def discover_agent_tools(
    registry: SkillRegistry,
    query: str = "",
    *,
    top_k: int = 10,
    caller_permissions: "frozenset[str] | set[str] | None" = None,
    metadata_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把 SkillRegistry 候选能力转为 LLM 工具描述（tool discovery → SkillRegistry）。

    架构契约：Planner / Agent 不应把全量 Skill schema 塞进 LLM 上下文，而是先经
    ``discover`` 缩窄候选集，再交 LLM 决策。返回的 schema 与 OpenAI function calling 同构。
    """
    candidates = registry.discover(
        query,
        top_k=top_k,
        caller_permissions=caller_permissions,
        metadata_filter=metadata_filter,
    )
    return SkillRegistry.to_tool_schemas(candidates)


class RuntimeToolCaller:
    """Agent tool call → 统一 Runtime 边界。

    架构验收 #4：Agentic tool/subagent 执行不能绕过 Skill Runtime。本调用器：
    - 仅允许调用注册表中的能力（未注册 → ``SkillNotFoundError``，拒绝任意执行器）；
    - 经 ``runtime.delegate`` 执行，受统一预算 / 权限 / 超时 / 熔断 / 追踪 / 轨迹治理。
    """

    def __init__(self, runtime: PlannerRuntime) -> None:
        self._runtime = runtime

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._runtime.registry:
            raise SkillNotFoundError(f"Agent 请求未注册能力（拒绝绕过 Runtime）: {name}")
        return await self._runtime.delegate(name, **(arguments or {}))

    async def __call__(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call(name, arguments)


class AgenticRuntimeBridge:
    """Agent loop 的统一 Runtime 入口聚合：工具发现 + 受治理工具调用。

    用法（框架无关）：
        bridge = AgenticRuntimeBridge(runtime)
        tools = bridge.discover(query)            # 注入 LLM 工具列表
        answer = await agent_loop(query, tools, bridge.call_tool)  # agent loop 经 call_tool 调用
    """

    def __init__(self, runtime: PlannerRuntime) -> None:
        self._runtime = runtime

    def discover(
        self,
        query: str = "",
        *,
        top_k: int = 10,
        caller_permissions: "frozenset[str] | set[str] | None" = None,
    ) -> list[dict[str, Any]]:
        return discover_agent_tools(
            self._runtime.registry,
            query,
            top_k=top_k,
            caller_permissions=caller_permissions,
        )

    @property
    def call_tool(self) -> RuntimeToolCaller:
        """供 agent loop 调用的受治理工具调用器。"""
        return RuntimeToolCaller(self._runtime)


__all__ = [
    "AgenticRuntimeBridge",
    "RuntimeToolCaller",
    "discover_agent_tools",
]
