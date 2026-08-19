"""元知识库 Postgres 仓储：列/指标/值信息 CRUD。"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class MetaRepository:
    """元知识库仓储。"""

    def __init__(self, pool=None, table_prefix: str = "wenda_data_agent_") -> None:
        self._pool = pool
        self._prefix = table_prefix

    async def save_column(self, data: dict[str, Any]) -> None:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {self._prefix}column_info ({cols}) VALUES ({placeholders})"
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def save_metric(self, data: dict[str, Any]) -> None:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {self._prefix}metric_info ({cols}) VALUES ({placeholders})"
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def save_value(self, data: dict[str, Any]) -> None:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {self._prefix}value_info ({cols}) VALUES ({placeholders})"
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def list_metrics(self) -> list[dict[str, Any]]:
        sql = f"SELECT metric_name, metric_desc, metric_expr FROM {self._prefix}metric_info"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql)
            rows = await cur.fetchall()
            return [dict(r._mapping) for r in rows]
