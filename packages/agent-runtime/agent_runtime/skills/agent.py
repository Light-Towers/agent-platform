"""AgentExecutor：本地 subagent 能力（联邦 database/network/knowledge 三 agent）。

形态：subagent dict（name/description/system_prompt/tools）→ 可独立执行的
LLM agent。与联邦 `_get_local_agent` 同一创建路径（deepagents.create_deep_agent），
lazy import 避免 import 期拉 LLM/tools 链。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.skills.registry import Skill, SkillKind


def as_agent_skill(
    subagent: dict,
    *,
    model: Any = None,
    timeout_ms: int | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> Skill:
    """把 subagent dict 包装为 agent 型能力。

    执行：每次调用创建独立 agent 实例并 invoke；kwargs 作为 agent 输入透传。
    model 必须为可调用 LLM（lazy import 时若为 None 由 create_deep_agent 报错）。
    """
    name = subagent.get("name") or "unknown"
    description = subagent.get("description", "")

    async def execute(**kwargs: Any) -> Any:
        from deepagents import create_deep_agent  # lazy：避免 import 期拉 LLM 链

        agent = create_deep_agent(
            model=model,
            name=name,
            description=description,
            system_prompt=subagent["system_prompt"],
            tools=list(subagent.get("tools", [])),
        )
        return await agent.ainvoke(kwargs)

    return Skill(
        name=name,
        description=description,
        kind=SkillKind.AGENT,
        executor=execute,
        timeout_ms=timeout_ms,
        input_schema=input_schema,
        output_schema=output_schema,
    )
