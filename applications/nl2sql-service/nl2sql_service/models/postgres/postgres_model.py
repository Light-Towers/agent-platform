"""Postgres 模型实现：纯 pydantic v2 + psycopg，无 MySQL 依赖。

2026-10-18（P0-10）：`create`/`update` 此前用 `data.keys()` 动态拼列名——
dict 来自调用方，键即 SQL 标识符位。改为列名逐个过白名单
（`agent_core.sql.identifiers`），值仍全参数化。
"""

from typing import Any

from agent_core.sql.identifiers import validate_identifier

from nl2sql_service.models.base import BaseModel


class PostgresModel(BaseModel):
    """Postgres CRUD 实现。"""

    def __init__(self, pool=None, table: str = "") -> None:
        super().__init__(pool=pool)
        validate_identifier(table, "表名")
        self._table = table

    async def create(self, data: dict[str, Any]) -> None:
        cols = [validate_identifier(c, "写入列名") for c in data]
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO {self._table} ({', '.join(cols)}) VALUES ({placeholders})"
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def read(self, key: Any) -> Any:
        sql = f"SELECT * FROM {self._table} WHERE id = %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (key,))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def update(self, key: Any, data: dict[str, Any]) -> None:
        cols = [validate_identifier(c, "更新列名") for c in data]
        sets = ", ".join(f"{c} = %s" for c in cols)
        sql = f"UPDATE {self._table} SET {sets} WHERE id = %s"
        async with self._pool.connection() as conn:
            await conn.execute(sql, (*data.values(), key))

    async def delete(self, key: Any) -> None:
        sql = f"DELETE FROM {self._table} WHERE id = %s"
        async with self._pool.connection() as conn:
            await conn.execute(sql, (key,))
