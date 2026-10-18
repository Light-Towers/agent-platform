"""pgvector 客户端管理：向量召回 + 全文检索 tsvector/ts_query。"""

import re
from collections.abc import Sequence
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

#: 至少含一个"词字符"（`\w` 含 CJK）才进 tsquery，纯标点 token 直接丢
_WORD_RE = re.compile(r"\w", re.UNICODE)
#: 单次 tsquery 的 lexeme 上限：关键词爆炸时防超长查询串
_TSQUERY_MAX_TERMS = 20


def build_tsquery(tokens: Sequence[str], max_terms: int = _TSQUERY_MAX_TERMS) -> str:
    """把已分词的 tokens 拼成 `to_tsquery` 表达式：``'tok1' | 'tok2'``。

    2026-10-18（方案 P0-5③ 查询侧）：此前用 `plainto_tsquery`，它把词之间按
    **AND** 连接——一个词没命中就整体空召回；对中文更糟：`'simple'` 配置不分词，
    整串当一个 lexeme，永远匹配不上 Python 侧切出来的 token。
    这里改为**显式 OR + 逐 token 单引号转义**，并保证：
    - token 来自同一个 Python 分词器（写入侧/查询侧单源，方案 B1 前半）；
    - `'` 双写转义，token 内的 `& | ! ( ) : *` 因被引号包住而按字面处理；
    - 空 token / 纯标点 token 丢弃；超过 `max_terms` 截断。

    ⚠️ 索引侧仍由 PG 的某个配置产出 tsvector（`nl2sql_value_info.value_tsvector`，
    生成方式仓内无 DDL，见方案 §2-④/Q23）。中文能否真正命中取决于索引侧分词，
    本函数只保证"查询表达式本身是对的"。
    """
    terms: list[str] = []
    for raw in tokens:
        for piece in str(raw).split():
            if not piece or not _WORD_RE.search(piece):
                continue
            terms.append("'" + piece.replace("'", "''") + "'")
            if len(terms) >= max_terms:
                return " | ".join(terms)
    return " | ".join(terms)


class PgvectorClientManager:
    """pgvector 向量召回 + Postgres 全文检索。"""

    def __init__(self, pool=None) -> None:
        self._pool = pool

    def set_pool(self, pool) -> None:
        self._pool = pool

    async def vector_search(
        self,
        table: str,
        embedding_col: str,
        query_embedding: list[float],
        top_k: int = 10,
        extra_cols: str = "*",
        filter_clause: str = "",
    ) -> list[dict[str, Any]]:
        sql = f"SELECT {extra_cols}, {embedding_col} <=> %s AS distance FROM {table}"
        if filter_clause:
            sql += f" WHERE {filter_clause}"
        sql += " ORDER BY distance LIMIT %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (query_embedding, top_k))
            rows = await cur.fetchall()
            return [dict(row._mapping) for row in rows]

    async def fulltext_search(
        self,
        table: str,
        tsvector_col: str,
        tokens: Sequence[str],
        top_k: int = 10,
        extra_cols: str = "*",
    ) -> list[dict[str, Any]]:
        """全文召回路：tokens 经 `build_tsquery` 变 OR 表达式后执行。

        入参从"整段 query 文本"改为"已分词的 tokens"（2026-10-18）：
        分词只做一次、只在一侧做，避免查询侧 Python 分词与 PG 侧
        `plainto_tsquery('simple')` 两套词表互相认不出。
        """
        tsquery = build_tsquery(tokens)
        if not tsquery:
            return []
        sql = (
            f"SELECT {extra_cols}, ts_rank({tsvector_col}, to_tsquery('simple', %s)) AS rank "
            f"FROM {table} "
            f"WHERE {tsvector_col} @@ to_tsquery('simple', %s) "
            f"ORDER BY rank DESC LIMIT %s"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (tsquery, tsquery, top_k))
            rows = await cur.fetchall()
            return [dict(row._mapping) for row in rows]

    async def upsert_vector(
        self,
        table: str,
        data: dict[str, Any],
        embedding_col: str,
        embedding: list[float],
        conflict_col: str = "id",
    ) -> None:
        cols = list(data.keys()) + [embedding_col]
        placeholders = ", ".join(["%s"] * (len(cols)))
        col_names = ", ".join(cols)
        sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_col}) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != conflict_col)
        )
        params = tuple(data.values()) + (embedding,)
        async with self._pool.connection() as conn:
            await conn.execute(sql, params)
