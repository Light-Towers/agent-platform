"""值信息 pgvector 仓储：向量 + 全文检索 tsvector。"""

from typing import Any

from wenda_data_agent.clients.pgvector_client_manager import PgvectorClientManager


class ValueRepository:
    """值信息向量 + 全文召回仓储。"""

    def __init__(self, pgvector_client: PgvectorClientManager, table: str = "wenda_value_info") -> None:
        self._client = pgvector_client
        self._table = table

    async def recall(self, keywords: list[str], embedding: list[float] | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        query_text = " ".join(keywords)
        if query_text:
            ft_results = await self._client.fulltext_search(
                table=self._table,
                tsvector_col="value_tsvector",
                query=query_text,
                top_k=top_k,
                extra_cols="column_name, value, value_desc",
            )
            results.extend(ft_results)
        if embedding and len(results) < top_k:
            vec_results = await self._client.vector_search(
                table=self._table,
                embedding_col="embedding",
                query_embedding=embedding,
                top_k=top_k - len(results),
                extra_cols="column_name, value, value_desc",
            )
            results.extend(vec_results)
        return results[:top_k]
