"""业务数仓 Postgres 仓储：只读执行。"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class DwRepository:
    """业务数仓只读仓储。"""

    def __init__(self, pool=None) -> None:
        self._pool = pool

    async def execute_readonly(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            await conn.execute("SET default_transaction_read_only = on")
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r._mapping) for r in rows]

    async def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        sql = (
            "SELECT column_name, data_type, column_comment "
            "FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position"
        )
        return await self.execute_readonly(sql, (table_name,))

    async def list_tables(self, schema: str = "public") -> list[dict[str, Any]]:
        sql = (
            "SELECT table_name, obj_description((quote_ident(table_schema)||'.'||quote_ident(table_name))::regclass) as table_comment "
            "FROM information_schema.tables WHERE table_schema = %s"
        )
        return await self.execute_readonly(sql, (schema,))
