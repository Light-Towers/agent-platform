"""RemoteExecutor：远程子服务能力（Agent Protocol / HTTP）。

形态：`async invoke(**kwargs) -> Any` 透传远程调用；invoke 由接入方提供
（如联邦 AsyncSubAgent 的 run 包装）。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent_runtime.skills.registry import Skill, SkillKind


def as_remote_skill(
    name: str,
    description: str,
    invoke: Callable[..., Awaitable[Any]],
    *,
    timeout_ms: int | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    permissions: frozenset[str] | set[str] | None = None,
) -> Skill:
    """把远程子服务调用包装为 remote 型能力。"""

    async def execute(**kwargs: Any) -> Any:
        return await invoke(**kwargs)

    return Skill(
        name=name,
        description=description,
        kind=SkillKind.REMOTE,
        executor=execute,
        timeout_ms=timeout_ms,
        input_schema=input_schema,
        output_schema=output_schema,
        permissions=frozenset(permissions) if permissions else frozenset(),
    )
