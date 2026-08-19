"""指标信息 pgvector 仓储：向量召回。"""

from typing import Any

from wenda_data_agent.clients.pgvector_client_manager import PgvectorClientManager


class MetricRepository:
    """指标信息向量召回仓储。"""

    def __init__(self, pgvector_client: PgvectorClientManager, table: str = "wenda_metric_info") -> None:
        self._client = pgvector_client
        self._table = table

    async def recall(self, keywords: list[str], embedding: list[float] | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        if embedding is None:
            return []
        return await self._client.vector_search(
            table=self._table,
            embedding_col="embedding",
            query_embedding=embedding,
            top_k=top_k,
            extra_cols="metric_name, metric_desc, metric_expr",
        )
