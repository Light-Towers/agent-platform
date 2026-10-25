-- nl2sql-service 元知识库 schema v4：范例库（A 方案 Stage ② 的落点，2026-10-18）
-- 生成参考：docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md §5.14-R4 + A 方案 Stage ②
--
-- 为什么需要这张表：agent_server/sql 的"训练三件套"退役时，`sql_examples`
-- （问题→SQL 范例，Vanna 式持续训练的第三件）必须整体迁入 nl2sql，否则退役
-- agent_server/sql = 丢掉 few-shot 范例召回能力（净倒退）。DDL→column_info、
-- docs→table_comment 都有现成落点，唯独范例没有——`nl2sql_session_state.
-- confirmed_pairs` 是**按 session 隔离的会话态**，塞全局训练语料既无自然
-- session 语义、又会被会话生命周期管理干扰，故新表承载。
--
-- 纪律同 001/002/003：幂等（IF NOT EXISTS）、不回改旧文件、无数据迁移、无 DROP。
-- 应用方式同 001：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"

CREATE TABLE IF NOT EXISTS nl2sql_example_info (
    id            BIGSERIAL PRIMARY KEY,
    -- 三个作用域列同 001 构型（P1-1/P1-6）：单租户 dev 默认 '' 匹配 DDL 默认行
    tenant_id     TEXT NOT NULL DEFAULT '',
    workspace_id  TEXT NOT NULL DEFAULT '',
    datasource_id TEXT NOT NULL DEFAULT '',
    question      TEXT NOT NULL,
    sql           TEXT NOT NULL DEFAULT '',
    -- 来源区分（同 alias_info.source 语义）：human=人工整理/历史训练数据迁移；
    -- machine=机提（未确认前不参与召回——错范例比没有范例更糟，见 §5.14-R1 同构逻辑）
    source        TEXT NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'machine')),
    embedding     vector({{vector_dim}}),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 自然键 = 问题（同一问法对应一条规范 SQL；重训练走 upsert 更新 SQL，
    -- 不叠加副本——与 column/metric/value 的幂等重建同构，方案 H3/P0-2）
    CONSTRAINT uq_nl2sql_example
        UNIQUE (tenant_id, workspace_id, datasource_id, question)
);
COMMENT ON TABLE nl2sql_example_info IS 'NL→SQL 范例库（A 方案 Stage ② 迁移落点）：按问题相似度向量召回，注入生成期 few-shot；机提范例未确认不召回';

-- ANN 索引：同 001 的 hnsw→ivfflat→告警 三级回退（查询用 <=> cosine）
DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_nl2sql_example_embedding
        ON nl2sql_example_info USING hnsw (embedding vector_cosine_ops);
EXCEPTION WHEN OTHERS THEN
    BEGIN
        CREATE INDEX IF NOT EXISTS idx_nl2sql_example_embedding
            ON nl2sql_example_info USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        RAISE WARNING 'example_info: hnsw 不可用（pgvector < 0.5?），已回退 ivfflat';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'example_info: ANN 索引创建失败（%），向量召回将顺序扫描', SQLERRM;
    END;
END $$;

INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '4')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
