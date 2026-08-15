"""pgvector 客户端管理：向量召回 + 全文检索 tsvector/ts_query。"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


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
        query: str,
        top_k: int = 10,
        extra_cols: str = "*",
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {extra_cols}, ts_rank({tsvector_col}, plainto_tsquery('simple', %s)) AS rank "
            f"FROM {table} "
            f"WHERE {tsvector_col} @@ plainto_tsquery('simple', %s) "
            f"ORDER BY rank DESC LIMIT %s"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (query, query, top_k))
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
