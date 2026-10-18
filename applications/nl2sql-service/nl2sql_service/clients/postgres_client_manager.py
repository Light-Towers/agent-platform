# -*- coding: utf-8 -*-
"""Postgres 客户端管理：CLI 构建入口用的连接池。

池参数走 `agent_runtime.pool_factory.create_pool`（2026-10-18 上移的共享件，
方案 §5.12.2）：与 `api/dependencies.py` 在线路径同一套工厂，避免"在线池有配额、
CLI 池裸奔"。DSN 打印一律脱敏（S-4：URL 格式的密码就在前 30 字符内，
`dsn[:30]` 那种截断等于明文泄露）。
"""

from agent_core.logging import get_logger
from agent_runtime.pool_factory import create_pool
from psycopg_pool import AsyncConnectionPool

logger = get_logger(__name__)


def redact_dsn(dsn: str) -> str:
    """日志用 DSN 脱敏：只留 `user@host:port/dbname`，密码永不进日志。

    走 libpq 自己的 conninfo 解析（`psycopg.conninfo.conninfo_to_dict`），
    不自己写正则——URL 与 key=value 两种格式、百分号编码、IPv6 字面量
    都由 libpq 处理。解析失败时返回占位符，绝不回退到"打印原文"。
    """
    try:
        from psycopg.conninfo import conninfo_to_dict

        info = conninfo_to_dict(dsn)
    except Exception:  # noqa: BLE001 - 解析器对畸形输入的异常类型不可精确预测；
        # 此路径的容忍度高于精确度：必须兜底返回占位符，绝不能崩或回退打印原文
        logger.warning("DSN 解析失败，日志已脱敏为占位符")
        return "<unparsable-dsn>"
    user = info.get("user") or "-"
    host = info.get("host") or "localhost"
    port = info.get("port") or "5432"
    db = info.get("dbname") or "-"
    return f"{user}@{host}:{port}/{db}"


class PostgresClientManager:
    """Postgres 异步连接池管理。"""

    def __init__(
        self,
        dsn: str,
        min_size: int = 1,
        max_size: int = 10,
        timeout: float = 5.0,
        statement_timeout_ms: int = 30000,
        name: str = "meta-cli",
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._timeout = timeout
        self._statement_timeout_ms = statement_timeout_ms
        self._name = name
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        self._pool = create_pool(
            dsn=self._dsn,
            name=self._name,
            min_size=self._min_size,
            max_size=self._max_size,
            timeout=self._timeout,
            statement_timeout_ms=self._statement_timeout_ms,
            # CLI 是构建入口，要写元知识库，不能只读
            read_only=False,
        )
        await self._pool.open()
        logger.info(
            "postgres pool opened: name=%s dsn=%s quota=%d-%d",
            self._name,
            redact_dsn(self._dsn),
            self._min_size,
            self._max_size,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("postgres pool closed: name=%s", self._name)

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("pool not connected, call connect() first")
        return self._pool
