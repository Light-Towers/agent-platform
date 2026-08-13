"""recall_column 节点：pgvector 向量召回列信息。"""

from typing import Any

from wenda_data_agent.agent.context import DataAgentContext


async def recall_column(state: dict[str, Any]) -> dict[str, Any]:
    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.column_repository is None:
        return {"columns": []}

    embedding: list[float] | None = None
    if ctx.embedding_client is not None:
        try:
            embedding = await ctx.embedding_client.embed_query(" ".join(keywords))
        except Exception:  # noqa: BLE001
            embedding = None

    columns = await ctx.column_repository.recall(keywords, embedding=embedding, top_k=10)
    return {"columns": columns}
