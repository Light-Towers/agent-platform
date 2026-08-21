"""PostgreSQL + pgvector 连接池（agent_federation 单一池，遵守 ADR-0003）。

设计要点：
- agent_federation 不自建 asyncpg 双池；pg 模式语义/类型记忆统一走此 psycopg 单池。
- 池 URL 取 ``AGENT_PLATFORM_DATABASE_URL``（WS-5：旧名 ``DEEPAGENTS_DATABASE_URL``
  兼容一个小版本，回退 ``DATABASE_URL``；与 app 共享库时指向同一库）。
- 懒加载加锁 + lifespan 预热，避免竞态；建表语句全部 IF NOT EXISTS，重启安全。
- ``register_vector_async`` 必须在打开连接池前先 ``CREATE EXTENSION vector``，否则报
  "vector type not found"（与 app/infra/db.py 同一坑）。
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = asyncio.Lock()

# agent_federation 仅用到 memories 表（类型化记忆）；其余表由 app 侧 schema 负责
MEMORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    embedding vector({dim}),
    memory_type TEXT NOT NULL DEFAULT 'semantic',
    importance FLOAT NOT NULL DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories (user_id, memory_type);
"""


def _database_url() -> str | None:
    # WS-5：经内核配置层解析（新名优先，旧名 DEEPAGENTS_DATABASE_URL 兼容 + 弃用警告）
    from agent_core.config import env_database_url

    return env_database_url() or None


def _vector_dim() -> int:
    """向量维度来自 embedder 单例（与落库 embedding 保持一致）。"""
    try:
        from agent_core.memory.embedder import get_embedder

        return int(get_embedder().dim)
    except Exception:
        return int(os.getenv("EMBEDDING_DIM", "512"))


async def init_pool():
    """lifespan 中调用一次；带锁防竞态。URL 未配置时返回 None（内存模式）。"""
    global _pool
    url = _database_url()
    if not url:
        logger.info("AGENT_PLATFORM_DATABASE_URL/DATABASE_URL 未配置，以内存模式运行（无持久化）")
        return None
    async with _pool_lock:
        if _pool is not None:
            return _pool
        from pgvector.psycopg import register_vector_async
        from psycopg import AsyncConnection
        from psycopg_pool import AsyncConnectionPool

        # 顺序约束：先建扩展，再开池（每个连接建立时 register_vector_async 会 fetch 'vector' 类型）
        async with await AsyncConnection.connect(url, autocommit=True) as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        pool = AsyncConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=int(os.getenv("DEEPAGENTS_DB_POOL_MAX", "10")),
            kwargs={"autocommit": True},
            configure=register_vector_async,
            open=False,
        )
        await pool.open(wait=True)
        await _ensure_schema(pool)
        _pool = pool
        logger.info("agent_federation PostgreSQL 连接池就绪，memories schema 已校验")
        return _pool


async def _ensure_schema(pool) -> None:
    """建表 + 幂等 ALTER（存量库补 memory_type/importance 列）。"""
    dim = _vector_dim()
    async with pool.connection() as conn:
        await conn.execute(MEMORIES_SCHEMA.format(dim=dim))
    for _ddl in (
        "ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'semantic'",
        "ALTER TABLE memories ADD COLUMN importance FLOAT NOT NULL DEFAULT 0.5",
        "CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories (user_id, memory_type)",
    ):
        try:
            async with pool.connection() as conn:
                await conn.execute(_ddl)
        except Exception:
            # duplicate_column / 索引已存在等幂等失败忽略
            pass


def get_pool():
    """已初始化则返回连接池，否则 None。不做隐式初始化（初始化只发生在 lifespan）。"""
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
