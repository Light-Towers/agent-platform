"""PostgreSQL + pgvector 连接池与幂等建表。

设计要点（吸取 deepagents 评审教训）：
- 懒加载必须加锁 + lifespan 预热，避免竞态；
- 建表语句全部 IF NOT EXISTS，重启安全。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = asyncio.Lock()

SCHEMA_TEMPLATE = """
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
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories (user_id);

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


async def init_pool(database_url: str = "", db_pool_max_size: int = 20):
    """lifespan 中调用一次；带锁防竞态。DATABASE_URL 未配置时返回 None（内存模式）。

    配置依赖倒置（Plan-F）：agent-runtime 不依赖 app.config，连接参数由调用方
    （app lifespan / scripts）从自身 Settings 注入；database_url 为空即内存模式。
    """
    global _pool
    if not database_url:
        logger.info("DATABASE_URL 未配置，以内存模式运行（无持久化）")
        return None
    async with _pool_lock:
        if _pool is not None:
            return _pool
        from pgvector.psycopg import register_vector_async
        from psycopg_pool import AsyncConnectionPool

        # 顺序约束：register_vector_async 在每个连接建立时即 fetch 'vector' 类型，
        # 故必须在打开连接池（建立首批连接）之前先启用 pgvector 扩展，
        # 否则报 "vector type not found in the database"（TB-7 真端到端暴露）。
        await ensure_extensions(database_url)

        pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=db_pool_max_size,  # 可配置，默认 20，避免高并发池耗尽
            kwargs={"autocommit": True},
            # 必须用 register_vector_async：AsyncConnectionPool 的连接是 AsyncConnection，
            # 同步版 register_vector 调用 TypeInfo.fetch 会返回未 await 的 coroutine，
            # 导致 'coroutine' object has no attribute 'register'（TB-7 真端到端暴露）。
            configure=register_vector_async,
            open=False,
        )
        await pool.open(wait=True)
        await ensure_schema(pool)
        _pool = pool
        logger.info("PostgreSQL 连接池就绪，schema 已校验")
        return _pool


async def ensure_extensions(database_url: str) -> None:
    """连接池建立前，用一次性连接启用 pgvector 扩展（幂等）。"""
    from psycopg import AsyncConnection

    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


async def ensure_schema(pool, vector_dim: int = 512) -> None:
    """幂等建表 + 存量库 ALTER。vector_dim 由调用方注入（配置依赖倒置）。"""
    ddl = SCHEMA_TEMPLATE.format(dim=vector_dim)
    async with pool.connection() as conn:
        await conn.execute(ddl)
    # 存量库迁移：新列 IF NOT EXISTS 不作用于已存在表，需幂等 ALTER（优化 G：workspace 隔离）
    try:
        async with pool.connection() as conn:
            await conn.execute(
                "ALTER TABLE chunks ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks (workspace_id)"
            )
    except Exception:
        # duplicate_column 等幂等失败忽略；新库由建表语句已含该列
        pass
    # 优化 H：长期记忆质量升级——memories 表扩展类型/重要性/时间元数据（幂等 ALTER）
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


async def ping() -> bool:
    """健康检查用：连接池存活即认为存储可用。"""
    if _pool is None:
        return False
    try:
        async with _pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
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

    安全：table/cols 经标识符白名单校验（仅含 [a-z0-9_]，列名逗号分隔），
    拒绝任意字符串注入，避免误用导致的 SQL 注入式表名/列名。
    """
    import re

    _IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
    if not _IDENT.match(table or ""):
        raise ValueError(f"vector_search: 非法表名 {table!r}（仅允许 [a-z0-9_]）")
    for _col in cols.split(","):
        _col = _col.strip()
        if not _col or not _IDENT.match(_col):
            raise ValueError(f"vector_search: 非法列名 {cols!r}（仅允许 [a-z0-9_]，逗号分隔）")
    sql = (
        f"SELECT {cols} FROM {table} WHERE {where} "
        f"ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    params = (*where_params, embedding, k)
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()
