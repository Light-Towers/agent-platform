"""FunctionExecutor：进程内确定性函数能力（app 侧 search/rag/sql/mcp）。

形态：`async fn(**kwargs) -> Any`，kwargs 由调用方按能力签名透传。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent_runtime.capabilities.registry import Capability, CapabilityKind


def as_function_capability(
    name: str,
    description: str,
    fn: Callable[..., Awaitable[Any]],
    *,
    timeout_ms: int | None = None,
) -> Capability:
    """把进程内 async 函数包装为 function 型能力。"""

    async def execute(**kwargs: Any) -> Any:
        return await fn(**kwargs)

    return Capability(
        name=name,
        description=description,
        kind=CapabilityKind.FUNCTION,
        executor=execute,
        timeout_ms=timeout_ms,
    )
