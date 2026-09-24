-- v1 baseline: 全量建表（等价原 SCHEMA_TEMPLATE）
-- 全新库首次启动时 apply；存量库由 runner baseline stamp 跳过。
-- {{vector_dim}} 由 runner 统一替换。

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL,
    source TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    embedding vector({{vector_dim}}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (doc_id);

CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    embedding vector({{vector_dim}}),
    memory_type TEXT NOT NULL DEFAULT 'semantic',
    importance FLOAT NOT NULL DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories (user_id);
CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories (user_id, memory_type);

CREATE TABLE IF NOT EXISTS semantic_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    embedding vector({{vector_dim}}),
    tenant_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_tenant ON semantic_cache (tenant_id);

CREATE TABLE IF NOT EXISTS sql_ddl (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector({{vector_dim}}),
    workspace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sql_ddl_workspace ON sql_ddl (workspace_id);

CREATE TABLE IF NOT EXISTS sql_docs (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector({{vector_dim}}),
    workspace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sql_docs_workspace ON sql_docs (workspace_id);

CREATE TABLE IF NOT EXISTS sql_examples (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    embedding vector({{vector_dim}}),
    workspace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
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

-- Durability PG
CREATE TABLE IF NOT EXISTS execution_checkpoints (
    execution_id TEXT PRIMARY KEY,
    completed JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resumable BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT NOT NULL DEFAULT 0,
    generation BIGINT,
    state_schema_version INTEGER NOT NULL DEFAULT 1
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
    expires_at TIMESTAMPTZ NOT NULL,
    generation BIGINT NOT NULL DEFAULT 1
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

-- Side effects
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

-- Execution events
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

-- Trajectories
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

-- V3: Execution status
CREATE TABLE IF NOT EXISTS execution_status (
    execution_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    generation BIGINT,
    reason TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}',
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_status_status ON execution_status (status);

-- V3: Awaitable tasks
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

-- V3: Execution queue
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

-- Cost governance
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

-- Episodic memory
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

-- Procedural memory
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
