"""指标信息 pgvector 仓储：向量召回 + 相对截断（P0-5④）。"""

from collections.abc import Sequence
from typing import Any

from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager, relative_truncate


class MetricRepository:
    """指标信息向量召回仓储。"""

    def __init__(self, pgvector_client: PgvectorClientManager, table: str = "nl2sql_metric_info") -> None:
        self._client = pgvector_client
        self._table = table

    async def recall(
        self,
        keywords: list[str],
        embedding: list[float] | None = None,
        top_k: int = 10,
        score_margin: float = 0.0,
        filters: Sequence[tuple[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        if embedding is None:
            return []
        rows = await self._client.vector_search(
            table=self._table,
            embedding_col="embedding",
            query_embedding=embedding,
            top_k=top_k,
            extra_cols="metric_name, metric_desc, metric_expr",
            filters=filters,
        )
        # 相对截断：与最佳分的差超过 margin 即丢（P0-5④）
        return relative_truncate(rows, score_margin)
