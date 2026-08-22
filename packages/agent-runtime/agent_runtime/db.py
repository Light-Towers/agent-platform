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
_closing = False  # 关闭进行中标记，防止关闭途中被重新拉起成双池

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

-- §20.1/20.2: Durability PG 后端表
CREATE TABLE IF NOT EXISTS execution_checkpoints (
    execution_id TEXT PRIMARY KEY,
    completed JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resumable BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_resumable ON execution_checkpoints (resumable) WHERE resumable;

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS execution_leases (
    execution_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leases_expires ON execution_leases (expires_at);

CREATE TABLE IF NOT EXISTS admission_slots (
    slot_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_slots_expires ON admission_slots (expires_at);

-- §HA: 副作用审计表（effectively-once 证据）
-- effect_key = execution_id + step_id + effect_type，唯一约束保证幂等写。
-- owner/attempt_id 用于最终审计「attempt 次数 vs actual effect 次数」。
CREATE TABLE IF NOT EXISTS side_effects (
    effect_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    effect_type TEXT NOT NULL,
    owner TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_side_effects_execution ON side_effects (execution_id);

-- §HA: 执行事件审计流（可证明的 trajectory 连续性证据）
CREATE TABLE IF NOT EXISTS execution_events (
    id BIGSERIAL PRIMARY KEY,
    execution_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    replica TEXT NOT NULL,
    event TEXT NOT NULL,
    step_id TEXT,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exec_events_execution ON execution_events (execution_id);
CREATE INDEX IF NOT EXISTS idx_exec_events_created ON execution_events (created_at);

-- §20.1/20.2/P3-1: Trajectory 轨迹存储
CREATE TABLE IF NOT EXISTS trajectories (
    execution_id TEXT PRIMARY KEY,
    parent_execution_id TEXT,
    session_id TEXT,
    planner TEXT,
    plan JSONB NOT NULL DEFAULT '{}',
    steps JSONB NOT NULL DEFAULT '[]',
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trajectories_session ON trajectories (session_id);
CREATE INDEX IF NOT EXISTS idx_trajectories_created ON trajectories (created_at);
"""


async def init_pool(
    database_url: str = "",
    db_pool_max_size: int = 20,
    vector_dim: int | None = None,
):
    """lifespan 中调用一次；带锁防竞态。DATABASE_URL 未配置时返回 None（内存模式）。

    配置依赖倒置（Plan-F）：agent-runtime 不依赖 app.config，连接参数由调用方
    （app lifespan / scripts）从自身 Settings 注入；database_url 为空即内存模式。

    vector_dim: 向量维度。未提供时从 agent_core.memory.embedder.get_embedder().dim
    自动派生（单一事实源）。仅当 embedder 不可用时才回退到默认 512。
    """
    global _pool
    if not database_url:
        logger.info("DATABASE_URL 未配置，以内存模式运行（无持久化）")
        return None
    async with _pool_lock:
        if _closing:
            logger.warning("连接池正在关闭，跳过初始化")
            return None
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
        await ensure_schema(pool, vector_dim=vector_dim)
        _pool = pool
        logger.info("PostgreSQL 连接池就绪，schema 已校验")
        return _pool


async def ensure_extensions(database_url: str) -> None:
    """连接池建立前，用一次性连接启用 pgvector 扩展（幂等）。"""
    from psycopg import AsyncConnection

    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


async def ensure_schema(pool, vector_dim: int | None = None) -> None:
    """幂等建表 + 存量库 ALTER。

    vector_dim 单一事实源：
    1. 调用方显式注入（配置依赖倒置）；
    2. 否则从 agent_core.memory.embedder.get_embedder().dim 自动派生；
    3. embedder 不可用时回退 512（兼容 mock/测试场景）。
    """
    if vector_dim is None:
        try:
            from agent_core.memory.embedder import get_embedder
            vector_dim = get_embedder().dim
            logger.debug("ensure_schema: vector_dim 从 embedder 派生 = %d", vector_dim)
        except Exception:
            vector_dim = 512
            logger.warning(
                "ensure_schema: embedder 不可用，回退默认 vector_dim=%d。"
                "生产环境建议显式注入或配置 EMBEDDING_DIM。",
                vector_dim,
            )
    # 用 replace 而非 format：SCHEMA 内部分 DDL（如 execution_checkpoints 的
    # DEFAULT '{}'）含裸花括号，str.format 会将其误判为占位符报 IndexError。
    ddl = SCHEMA_TEMPLATE.replace("{dim}", str(vector_dim))
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
    """优雅关闭连接池（多副本 SIGTERM → lifespan shutdown 路径）。

    设计要点（消除关闭竞态）：
    - 先置 ``_closing`` 并在锁内将全局 ``_pool`` 摘掉（置 None），使新请求
      ``get_pool()`` 立即返回 None（优雅降级），不会从「关闭中」的池借用连接。
    - 退出锁后再 ``await pool.close(timeout=30)``：优雅等待在途连接归还，
      timeout 为等待上限，**不等于强关、不取消在途请求**；达到上限后允许
      关闭流程继续，不阻塞进程退出。
    - ``close()`` 自身异常被记录且 ``_closing`` 复位，绝不永久卡死 runtime。
    - 并发/重复调用安全（幂等）。
    """
    global _pool, _closing
    async with _pool_lock:
        if _pool is None or _closing:
            return
        _closing = True
        pool = _pool
        _pool = None  # 立即摘掉全局引用，避免新请求从关闭中池借用连接
    try:
        await pool.close(timeout=30)
    except Exception as e:
        logger.warning("连接池关闭异常（忽略，进程即将退出）: %s", e)
    finally:
        _closing = False


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
