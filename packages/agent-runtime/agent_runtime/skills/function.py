"""FunctionExecutor：进程内确定性函数能力（app 侧 search/rag/sql/mcp）。

形态：`async fn(**kwargs) -> Any`，kwargs 由调用方按能力签名透传。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent_runtime.skills.registry import Skill, SkillKind


def as_function_skill(
    name: str,
    description: str,
    fn: Callable[..., Awaitable[Any]],
    *,
    timeout_ms: int | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> Skill:
    """把进程内 async 函数包装为 function 型能力。

    input_schema / output_schema（可选 JSON Schema dict）：Skill 契约（Phase 1.5），
    供 Planner / Agent 经 ``to_tool_schema()`` 生成工具描述。
    """

    async def execute(**kwargs: Any) -> Any:
        return await fn(**kwargs)

    return Skill(
        name=name,
        description=description,
        kind=SkillKind.FUNCTION,
        executor=execute,
        timeout_ms=timeout_ms,
        input_schema=input_schema,
        output_schema=output_schema,
    )
