"""PostgreSQL + pgvector 连接池（agent_federation 单一池，遵守 ADR-0003）。

设计要点：
- agent_federation 不自建 asyncpg 双池；pg 模式语义/类型记忆统一走 agent_runtime 单池。
- 池 URL 取 ``AGENT_PLATFORM_DATABASE_URL``（WS-5：旧名 ``DEEPAGENTS_DATABASE_URL``
  兼容一个小版本，回退 ``DATABASE_URL``；与 app 共享库时指向同一库）。
- 懒加载加锁 + lifespan 预热，避免竞态；建表语句全部 IF NOT EXISTS，重启安全。
- ``register_vector_async`` 必须在打开连接池前先 ``CREATE EXTENSION vector``，否则报
  "vector type not found"（与 app/infra/db.py 同一坑）。
- agent_federation 仅用到 memories 表（类型化记忆）；其余表由 app 侧 schema 负责。
"""

from __future__ import annotations

import logging

from agent_runtime.db import (
    get_pool,
)

logger = logging.getLogger(__name__)

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


# init_pool, get_pool, close_pool 已从 agent_runtime.db 导入，直接复用


async def _ensure_memories_schema() -> None:
    """确保 agent_federation 专用的 memories 表存在。"""
    pool = get_pool()
    if pool is None:
        return

    try:
        from agent_core.memory.embedder import get_embedder
        dim = get_embedder().dim
    except Exception:
        dim = 512

    ddl = f"""
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
    async with get_pool().connection() as conn:
        await conn.execute(ddl)

    # 存量库迁移：新列 IF NOT EXISTS 不作用于已存在表，需幂等 ALTER
    for _ddl in (
        "ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'semantic'",
        "ALTER TABLE memories ADD COLUMN importance FLOAT NOT NULL DEFAULT 0.5",
        "CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories (user_id, memory_type)",
    ):
        try:
            async with get_pool().connection() as conn:
                await conn.execute(_ddl)
        except Exception:
            # duplicate_column / 索引已存在等幂等失败忽略
            pass