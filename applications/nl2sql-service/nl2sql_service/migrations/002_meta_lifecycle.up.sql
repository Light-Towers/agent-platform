-- nl2sql-service 元知识库 schema v2：会话状态 / 查询追溯 / 表统计（2026-10-18）
-- 生成参考：docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md
--   §5.13（多轮 session 四元组）、P0-4（trace + golden 读数）、P0-3（漂移表统计）
--
-- 应用方式同 001：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"
--
-- 纪律（与 001 相同）：
--   1. 全部幂等（IF NOT EXISTS），可重复执行；不含 DROP、不含数据迁移。
--   2. 不回改 001；本文件是 v2 增量的唯一真相源。
--   3. 三张新表都带 tenant/workspace/datasource 作用域列（默认 ''，与 001 同构），
--      多租户落地时去默认、回填历史行、查询侧强制带谓词。

-- ---------------------------------------------------------------------------
-- 1. 会话状态（§5.13 多轮继承）：四元组 + 已确认 NL→SQL 对
--    唯一键含 datasource_id：换源 = 上下文清零重来（M4），不是覆盖
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_session_state (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT '',
    workspace_id    TEXT NOT NULL DEFAULT '',
    session_id      TEXT NOT NULL,
    datasource_id   TEXT NOT NULL DEFAULT '',
    turn            INTEGER NOT NULL DEFAULT 0,
    -- 继承四元组（M2）：时间窗 / 实体 / 候选表 / 已生成 SQL。
    -- 刻意不存 retrieved_info 大文本——随 schema 漂移快速 stale 且每轮 prompt 膨胀。
    quadruple       JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- 已确认的 NL→SQL 对（M6）：人不确认的（错题）不进范例库，只进 trace
    confirmed_pairs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_nl2sql_session
        UNIQUE (tenant_id, workspace_id, session_id, datasource_id)
);
CREATE INDEX IF NOT EXISTS idx_nl2sql_session_lookup
    ON nl2sql_session_state (session_id, datasource_id);

-- ---------------------------------------------------------------------------
-- 2. 查询追溯（P0-4）：每次问答一行，golden 回归与未命中字面量日报的数据源
--    记 meta_revision 与 source_snapshot：错答复现要靠"当时用的是哪版元知识"
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_query_trace (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL DEFAULT '',
    workspace_id     TEXT NOT NULL DEFAULT '',
    session_id       TEXT NOT NULL DEFAULT '',
    datasource_id    TEXT NOT NULL DEFAULT '',
    turn             INTEGER NOT NULL DEFAULT 0,
    query            TEXT NOT NULL,
    -- 多轮改写后的 query（M3：原始 query 不改写，trace 能看前后）
    rewritten_query  TEXT NOT NULL DEFAULT '',
    sql              TEXT NOT NULL DEFAULT '',
    error            TEXT NOT NULL DEFAULT '',
    error_class      TEXT NOT NULL DEFAULT '',
    error_detail     TEXT NOT NULL DEFAULT '',
    recalled_tables  JSONB NOT NULL DEFAULT '[]'::jsonb,
    recalled_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    recalled_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
    recalled_values  JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- P0-8④ 的返回体语义同源：matched/unmatched/dict_hit
    matched_values   JSONB NOT NULL DEFAULT '[]'::jsonb,
    unmatched_terms  JSONB NOT NULL DEFAULT '[]'::jsonb,
    dict_hit         BOOLEAN NOT NULL DEFAULT FALSE,
    llm_calls        INTEGER NOT NULL DEFAULT 0,
    embedding_calls  INTEGER NOT NULL DEFAULT 0,
    latency_ms       DOUBLE PRECISION NOT NULL DEFAULT 0,
    meta_revision    BIGINT NOT NULL DEFAULT 0,
    source_snapshot  TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL DEFAULT '',
    prompt_version   TEXT NOT NULL DEFAULT '',
    result_rows      INTEGER NOT NULL DEFAULT 0,
    empty_result     BOOLEAN NOT NULL DEFAULT FALSE,
    -- graph | metric_direct | refuse（P2 双路径一致性的对比维度）
    path             TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_nl2sql_trace_created
    ON nl2sql_query_trace (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nl2sql_trace_session
    ON nl2sql_query_trace (session_id, turn);

-- ---------------------------------------------------------------------------
-- 3. 表统计（P0-3 漂移检测的副产物）：行数估值驱动生成期聚合引导（§5.11-V3-3）
--    估值是估算值（reltuples/TABLE_ROWS），不是精确 count——引导用不着精确
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_table_stats (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT '',
    workspace_id  TEXT NOT NULL DEFAULT '',
    datasource_id TEXT NOT NULL DEFAULT '',
    table_name    TEXT NOT NULL,
    row_estimate  BIGINT NOT NULL DEFAULT 0,
    column_count  INTEGER NOT NULL DEFAULT 0,
    sampled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_nl2sql_table_stats
        UNIQUE (tenant_id, workspace_id, datasource_id, table_name)
);

-- schema 版本标记（与 001 同形状）
INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '2')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
