"""值信息 pgvector 仓储：码表字面检索（P0-5 取值路退役后的形态）。

2026-10-18（P0-5① / §5.3 落位表）：此前是"全文（simple 词典对中文整串
当词）+ 向量补位"——中文长文本模糊匹配在 PG 侧实际不可用（B1），向量路
对低基数码表又是杀鸡用牛刀。现在：

- **精确/前缀**：大小写不敏感等值 + 前缀（短文本召回的 L1 主路，
  词条 ≤2,000 别建向量/倒排）；
- **模糊自由文本**：不在 PG 做——改由只读探针（P0-9 `ValueResolver`）
  在数据所在的源侧完成，PG 只存**定义出来的码表**（D7 二分）。

注意：`nl2sql_value_info` 的 `embedding` 列由构建方写入（001 DDL 契约、
P0-1 判据），但召回路不再消费它——码表召回不需要 ANN。
"""

from collections.abc import Sequence
from typing import Any

from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager


class ValueRepository:
    """值信息仓储：码表精确/前缀召回。"""

    def __init__(self, pgvector_client: PgvectorClientManager, table: str = "nl2sql_value_info") -> None:
        self._client = pgvector_client
        self._table = table

    async def recall(
        self,
        keywords: list[str],
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: Sequence[tuple[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        """码表召回：token 过字面检索（等值 + 前缀）。embedding 形参保留但不再消费。"""
        if not keywords:
            return []
        return await self._client.literal_search(
            table=self._table,
            value_col="value",
            tokens=keywords,
            top_k=top_k,
            extra_cols="column_name, value, value_desc",
            filters=filters,
        )
