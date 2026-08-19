"""recall_value 节点：pgvector 全文召回值信息。"""

from typing import Any

from wenda_data_agent.agent.context import DataAgentContext


async def recall_value(state: dict[str, Any]) -> dict[str, Any]:
    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.value_repository is None:
        return {"values": []}

    values = await ctx.value_repository.recall(keywords, embedding=None, top_k=10)
    return {"values": values}
