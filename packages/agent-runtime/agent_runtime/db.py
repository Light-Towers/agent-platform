"""PostgreSQL + pgvector 连接池与 schema 迁移。

设计要点（吸取 deepagents 评审教训）：
- 懒加载必须加锁 + lifespan 预热，避免竞态；
- Schema 管理统一委托 agent_runtime.migrations.runner（P1-4 轻量版迁移系统）。
- SCHEMA_TEMPLATE 保留为参考（Phase B 将删除），实际建表由 001_baseline migration 执行。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = asyncio.Lock()
_closing = False  # 关闭进行中标记，防止关闭途中被重新拉起成双池

# DEPRECATED (P1-4 Phase A): 保留为参考，实际建表由 migrations/001_baseline.py 执行。
# Phase B 将删除此常量。
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
    tenant_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_semantic_cache_tenant ON semantic_cache (tenant_id);

CREATE TABLE IF NOT EXISTS sql_ddl (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector({dim}),
    workspace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE sql_ddl ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_sql_ddl_workspace ON sql_ddl (workspace_id);

CREATE TABLE IF NOT EXISTS sql_docs (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector({dim}),
    workspace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE sql_docs ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_sql_docs_workspace ON sql_docs (workspace_id);

CREATE TABLE IF NOT EXISTS sql_examples (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    embedding vector({dim}),
    workspace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE sql_examples ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_sql_examples_workspace ON sql_examples (workspace_id);

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
    resumable BOOLEAN NOT NULL DEFAULT FALSE,
    -- §HA（C3 checkpoint fencing）：单调 version = 已完成节点数，防止 stale writer 降级覆盖
    version BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_resumable ON execution_checkpoints (resumable) WHERE resumable;
-- 兼容已有表：幂等补列
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0;
-- V3-1: checkpoint 关联的 ownership generation（NULL = 向后兼容旧 checkpoint，仅按 version fencing）
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS generation BIGINT;
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS state_schema_version INTEGER NOT NULL DEFAULT 1;

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
-- V3-1: strict fencing generation（ownership epoch，与 checkpoint version 解耦）
-- takeover（不同 owner 抢过期 lease）时 generation = old + 1；同 owner 不递增
ALTER TABLE execution_leases ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 1;

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

-- V3-3: Execution 一等状态（durable status state machine）
CREATE TABLE IF NOT EXISTS execution_status (
    execution_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    generation BIGINT,
    reason TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}',
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_status_status ON execution_status (status);

-- V3-3: 可等待任务（External / Human / Timer / Callback durable execution）
CREATE TABLE IF NOT EXISTS awaitable_tasks (
    task_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    provider TEXT NOT NULL,
    state TEXT NOT NULL,
    provider_task_id TEXT,
    submission_receipt JSONB,
    completion_receipt JSONB,
    submitted_at DOUBLE PRECISION,
    completed_at DOUBLE PRECISION,
    deadline DOUBLE PRECISION,
    resume_payload JSONB,
    metadata JSONB NOT NULL DEFAULT '{}',
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_awaitable_execution ON awaitable_tasks (execution_id);
CREATE INDEX IF NOT EXISTS idx_awaitable_state ON awaitable_tasks (state);

-- V3-4A: Execution Scheduler 调度队列
CREATE TABLE IF NOT EXISTS execution_queue (
    execution_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at DOUBLE PRECISION NOT NULL,
    dispatched_at DOUBLE PRECISION,
    worker_id TEXT,
    resource_hints JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_exec_queue_status ON execution_queue (status);
CREATE INDEX IF NOT EXISTS idx_exec_queue_priority ON execution_queue (priority, created_at);
CREATE INDEX IF NOT EXISTS idx_exec_queue_tenant ON execution_queue (tenant_id, status);

-- V3 Phase 3: Cost Governance 预算表
CREATE TABLE IF NOT EXISTS budget_usage (
    tenant_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    bucket_index BIGINT NOT NULL,
    used DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, dimension, bucket_index)
);

CREATE TABLE IF NOT EXISTS budget_limits (
    tenant_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    limit_value DOUBLE PRECISION NOT NULL,
    window_seconds INTEGER NOT NULL DEFAULT 3600,
    PRIMARY KEY (tenant_id, dimension)
);

-- V3 Phase 4: CostRecord 可追溯成本记录
CREATE TABLE IF NOT EXISTS cost_records (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT,
    agent_run_id TEXT,
    execution_id TEXT NOT NULL,
    step_id TEXT,
    model TEXT,
    skill_name TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    actual_cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    timestamp DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cost_records_tenant ON cost_records (tenant_id);
CREATE INDEX IF NOT EXISTS idx_cost_records_execution ON cost_records (execution_id);
CREATE INDEX IF NOT EXISTS idx_cost_records_timestamp ON cost_records (timestamp);

-- 四类 Memory: Episodic Memory 持久化
CREATE TABLE IF NOT EXISTS episodic_memories (
    episode_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    task_summary TEXT NOT NULL,
    outcome TEXT NOT NULL,
    key_steps JSONB NOT NULL DEFAULT '[]',
    lessons JSONB NOT NULL DEFAULT '[]',
    skill_names JSONB NOT NULL DEFAULT '[]',
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    duration DOUBLE PRECISION NOT NULL DEFAULT 0,
    importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_at DOUBLE PRECISION NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_episodic_execution ON episodic_memories (execution_id);
CREATE INDEX IF NOT EXISTS idx_episodic_importance ON episodic_memories (importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_task ON episodic_memories (task_summary);

-- 四类 Memory: Procedural Memory 持久化（Skill 定义落库）
CREATE TABLE IF NOT EXISTS procedural_memories (
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    input_schema JSONB,
    output_schema JSONB,
    effect_contract JSONB,
    lifecycle TEXT NOT NULL DEFAULT 'stable',
    definition JSONB NOT NULL DEFAULT '{}',
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (name, version)
);
CREATE INDEX IF NOT EXISTS idx_procedural_name ON procedural_memories (name);
CREATE INDEX IF NOT EXISTS idx_procedural_lifecycle ON procedural_memories (lifecycle);
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
    """委托迁移 runner 执行 schema 管理（P1-4 轻量版）。

    原逻辑（CREATE IF NOT EXISTS 大模板 + ALTER try/except: pass）已重构为：
    - migrations/001_baseline.up.sql：全量建表
    - migrations/002_*.up.sql / 003_*.up.sql：增量 ALTER
    - runner：advisory_xact_lock + 事务 + 版本追踪 + 模板替换

    vector_dim 参数保留以兼容现有调用方（init_pool 传入），
    runner 内部统一从 embedder 解析维度并替换 SQL 模板。
    """
    from agent_runtime.migrations.runner import run_migrations

    applied = await run_migrations(pool)
    if applied:
        logger.info(
            "ensure_schema: %d migration(s) applied, now at version %d",
            len(applied),
            applied[-1].version,
        )
    else:
        logger.debug("ensure_schema: schema already up-to-date")


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
