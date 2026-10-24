"""范例库 pgvector 仓储：按问题相似度向量召回 + 相对截断（A 方案 Stage ②）。

与 Column/Metric/Value 三仓储同构（同 client、同 relative_truncate），差异两点：
1. 嵌入对象是 **question**（召"与当前问题相似的历史问题"），SQL 只是命中后
   注入 prompt 的 few-shot 参考文本。
2. `source='human'` 恒过滤：机提范例（未来从 confirmed_pairs 自动提升）未经人
   确认不进召回——错范例比没有范例更糟（同 alias_info.source 语义）。
"""

from collections.abc import Sequence
from typing import Any

from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager, relative_truncate


class ExampleRepository:
    """NL→SQL 范例向量召回仓储。"""

    def __init__(self, pgvector_client: PgvectorClientManager, table: str = "nl2sql_example_info") -> None:
        self._client = pgvector_client
        self._table = table

    async def recall(
        self,
        keywords: list[str],
        embedding: list[float] | None = None,
        top_k: int = 3,
        score_margin: float = 0.0,
        filters: Sequence[tuple[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        if embedding is None:
            return []
        # 机提范例不参与召回（source 恒 'human'）：附加在调用方 filters 之后，
        # 同一 AND 语义，不覆盖调用方的作用域条件。
        rows = await self._client.vector_search(
            table=self._table,
            embedding_col="embedding",
            query_embedding=embedding,
            top_k=top_k,
            extra_cols="question, sql, source",
            filters=(*filters, ("source", "human")),
        )
        # 相对截断：与最佳分的差超过 margin 即丢（绝对分跨查询不可比，P0-5④）
        return relative_truncate(rows, score_margin)
