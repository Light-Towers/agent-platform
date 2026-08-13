"""Postgres 客户端管理：psycopg AsyncConnectionPool。"""

from typing import Any

from agent_core.logging import get_logger
from psycopg import AsyncConnectionPool

logger = get_logger(__name__)


class PostgresClientManager:
    """Postgres 异步连接池管理。"""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        self._pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            open=True,
        )
        logger.info("postgres pool opened: dsn=%s", self._dsn[:30])

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("postgres pool closed")

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("pool not connected, call connect() first")
        return self._pool

    async def execute(self, sql: str, params: tuple | None = None) -> Any:
        async with self.pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return await cur.fetchall()

    async def execute_readonly(self, sql: str, params: tuple | None = None) -> Any:
        async with self.pool.connection() as conn:
            await conn.execute("SET default_transaction_read_only = on")
            cur = await conn.execute(sql, params)
            return await cur.fetchall()
