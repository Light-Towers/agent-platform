"""add_extra_context 节点：额外语义补充。"""

from typing import Any


async def add_extra_context(state: dict[str, Any]) -> dict[str, Any]:
    extra = state.get("extra_context", "")
    return {"extra_context": extra}
