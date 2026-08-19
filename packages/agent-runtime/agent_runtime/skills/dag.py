"""WorkflowExecutor（Static DAG）：把确定性编排包装为 workflow 型能力（Phase 3）。

形态：`async run_dag(**kwargs) -> Any`——内部执行静态 DAG（如 LangGraph 静态图
graph.astream 全链路），对调用方（Planner / Agent）保持黑盒：只见 Skill 契约
（name/description/input_schema/output_schema），不见内部节点。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent_runtime.skills.registry import Skill, SkillKind


def as_dag_skill(
    name: str,
    description: str,
    run_dag: Callable[..., Awaitable[Any]],
    *,
    timeout_ms: int | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> Skill:
    """把静态 DAG 执行器包装为 workflow 型能力。

    与 as_function_skill 同构，kind 为 WORKFLOW（语义区分：内部是编排而非单工具），
    供 Agent 组合调用（agentic 路径）或直接按 Skill 契约执行（deterministic 路径）。
    """

    async def execute(**kwargs: Any) -> Any:
        return await run_dag(**kwargs)

    return Skill(
        name=name,
        description=description,
        kind=SkillKind.WORKFLOW,
        executor=execute,
        timeout_ms=timeout_ms,
        input_schema=input_schema,
        output_schema=output_schema,
    )
