"""PostgreSQL + pgvector 连接池与幂等建表。

设计要点（吸取 deepagents 评审教训）：
- 懒加载必须加锁 + lifespan 预热，避免竞态；
- 建表语句全部 IF NOT EXISTS，重启安全。
"""

import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = asyncio.Lock()

SCHEMA_TEMPLATE = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL,
    source TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    embedding vector({dim}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (doc_id);

CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    embedding vector({dim}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS semantic_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    embedding vector({dim}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sql_ddl (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector({dim}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sql_docs (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector({dim}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sql_examples (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    embedding vector({dim}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admission_queue (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    admitted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    queue_position INTEGER,
    rejection_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_admission_status_priority ON admission_queue (status, created_at);
CREATE INDEX IF NOT EXISTS idx_admission_session ON admission_queue (session_id);
CREATE INDEX IF NOT EXISTS idx_admission_user ON admission_queue (user_id);

CREATE TABLE IF NOT EXISTS revert_audit (
    revert_id TEXT PRIMARY KEY,
    operator TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_checkpoint_id TEXT NOT NULL,
    target_checkpoint_id TEXT NOT NULL,
    reverted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revert_session ON revert_audit (session_id);
CREATE INDEX IF NOT EXISTS idx_revert_operator ON revert_audit (operator);

CREATE TABLE IF NOT EXISTS mcp_call_audit (
    call_id TEXT PRIMARY KEY,
    caller TEXT NOT NULL,
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    params_summary TEXT NOT NULL,
    result_summary TEXT,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    called_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_server ON mcp_call_audit (server_id);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_caller ON mcp_call_audit (caller);
"""


async def init_pool():
    """lifespan 中调用一次；带锁防竞态。DATABASE_URL 未配置时返回 None（内存模式）。"""
    global _pool
    settings = get_settings()
    if not settings.db_enabled:
        logger.info("DATABASE_URL 未配置，以内存模式运行（无持久化）")
        return None
    async with _pool_lock:
        if _pool is not None:
            return _pool
        from pgvector.psycopg import register_vector
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=settings.db_pool_max_size,  # 可配置，默认 20，避免高并发池耗尽
            kwargs={"autocommit": True},
            configure=register_vector,
            open=False,
        )
        await pool.open(wait=True)
        await ensure_schema(pool)
        _pool = pool
        logger.info("PostgreSQL 连接池就绪，schema 已校验")
        return _pool


async def ensure_schema(pool) -> None:
    ddl = SCHEMA_TEMPLATE.format(dim=get_settings().vector_dim)
    async with pool.connection() as conn:
        await conn.execute(ddl)


def get_pool():
    """已初始化则返回连接池，否则 None。不做隐式初始化（初始化只发生在 lifespan）。"""
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping() -> bool:
    """健康检查用：连接池存活即认为存储可用。"""
    if _pool is None:
        return False
    try:
        async with _pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 健康检查必须吞异常
        return False


async def vector_search(
    pool,
    table: str,
    cols: str,
    embedding: list[float],
    k: int = 1,
    where: str = "embedding IS NOT NULL",
    where_params: tuple = (),
) -> list[tuple]:
    """pgvector 余弦距离向量检索（app 包内通用）。

    SQL: SELECT {cols} FROM {table} WHERE {where} ORDER BY embedding <=> %s LIMIT %s
    """
    sql = (
        f"SELECT {cols} FROM {table} WHERE {where} "
        f"ORDER BY embedding <=> %s LIMIT %s"
    )
    params = (*where_params, embedding, k)
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()
