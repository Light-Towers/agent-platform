"""recall_value 节点：pgvector 全文召回值信息。

入参 metric_config 携带值定义时优先使用，不查预置元知识库。
"""

from typing import Any

from nl2sql_service.agent.context import DataAgentContext


async def recall_value(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        values = metric_config.get("values", [])
        return {"values": list(values)}

    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.value_repository is None:
        return {"values": []}

    values = await ctx.value_repository.recall(keywords, embedding=None, top_k=10)
    return {"values": values}
