"""Postgres 模型实现：纯 pydantic v2 + psycopg，无 MySQL 依赖。"""

from typing import Any

from wenda_data_agent.models.base import BaseModel


class PostgresModel(BaseModel):
    """Postgres CRUD 实现。"""

    def __init__(self, pool=None, table: str = "") -> None:
        super().__init__(pool=pool)
        self._table = table

    async def create(self, data: dict[str, Any]) -> None:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {self._table} ({cols}) VALUES ({placeholders})"
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def read(self, key: Any) -> Any:
        sql = f"SELECT * FROM {self._table} WHERE id = %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (key,))
            rows = await cur.fetchall()
            return [dict(r._mapping) for r in rows]

    async def update(self, key: Any, data: dict[str, Any]) -> None:
        sets = ", ".join(f"{k} = %s" for k in data)
        sql = f"UPDATE {self._table} SET {sets} WHERE id = %s"
        async with self._pool.connection() as conn:
            await conn.execute(sql, (*data.values(), key))

    async def delete(self, key: Any) -> None:
        sql = f"DELETE FROM {self._table} WHERE id = %s"
        async with self._pool.connection() as conn:
            await conn.execute(sql, (key,))
