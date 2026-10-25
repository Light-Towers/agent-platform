"""列信息 pgvector 仓储：向量召回 + 相对截断（P0-5④）。"""

from collections.abc import Sequence
from typing import Any

from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager, relative_truncate


class ColumnRepository:
    """列信息向量召回仓储。"""

    def __init__(self, pgvector_client: PgvectorClientManager, table: str = "nl2sql_column_info") -> None:
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
            # table_comment 随列行冗余带回（§5.14-R2）：业务文档（A 方案 Stage ②
            # 从 sql_docs 迁入）经 merge 派生进表清单，生成期 prompt 才看得到。
            extra_cols="column_name, column_comment, table_name, data_type, table_comment",
            filters=filters,
        )
        # 相对截断：与最佳分的差超过 margin 即丢（绝对分跨查询不可比，P0-5④）
        return relative_truncate(rows, score_margin)
