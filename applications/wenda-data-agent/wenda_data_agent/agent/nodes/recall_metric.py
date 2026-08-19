"""recall_metric 节点：pgvector 向量召回指标信息。"""

from typing import Any

from wenda_data_agent.agent.context import DataAgentContext


async def recall_metric(state: dict[str, Any]) -> dict[str, Any]:
    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.metric_repository is None:
        return {"metrics": []}

    embedding: list[float] | None = None
    if ctx.embedding_client is not None:
        try:
            embedding = await ctx.embedding_client.embed_query(" ".join(keywords))
        except Exception:
            embedding = None

    metrics = await ctx.metric_repository.recall(keywords, embedding=embedding, top_k=10)
    return {"metrics": metrics}
