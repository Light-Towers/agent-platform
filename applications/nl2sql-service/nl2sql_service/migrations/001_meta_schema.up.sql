-- nl2sql-service 元知识库 schema（v1）
-- 生成：2026-10-18    参考：docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md §5.17
--
-- 应用方式（二选一）：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"
--   psql "$META_DB_DSN" -f nl2sql_service/migrations/001_meta_schema.up.sql   -- 需先把 vector_dim 占位符替换成实际维度
--
-- 模板变量：文件内 vector_dim 占位符（双花括号包住 vector_dim）由 init_meta_schema
-- 按 Settings.vector_dim（默认 1536）替换，必须与 embedding 模型输出维度一致；
-- 换模型 = 新维度 = 新库或全量重灌（ALTER TYPE 会重写全表）。
--
-- 纪律：
--   1. 本文件是这五张表 + 版本标记表的唯一真相源（此前仓内无任何 DDL，见方案 §2-④/N4）。
--   2. 改 schema 一律新增 002_*.up.sql，不回改本文件（已应用环境靠 IF NOT EXISTS 幂等重跑）。
--   3. 所有语句幂等，可重复执行；不含 DROP、不含数据迁移。
--
-- 表间关系（无物理外键，均为逻辑关联，理由：元知识按 batch 重建，FK 会拖慢批量写入）：
--   column_info.datasource_id + table_name ─┬─> relation_info.left_table / right_table
--                                           └─> value_info.column_name
--   alias_info.target_kind + target_name ───> 上述任一对象（table / column / metric）

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- 0. schema 版本标记：回答"这个库停在哪一版 DDL"
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_schema_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '1')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

-- ---------------------------------------------------------------------------
-- 1. 列级元知识：ColumnRepository 向量召回 / MetaRepository.save_column 写入
--    代码读到的列：column_name, column_comment, table_name, data_type, embedding
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_column_info (
    id             BIGSERIAL PRIMARY KEY,
    -- 三个作用域列是 P1-1 / P1-6 的前置槽位：当前写入方不传，故给空串默认；
    -- 多租户落地时必须去掉默认、回填历史行，并在查询侧强制带谓词（禁止"空 = 全库"旁路）。
    tenant_id      TEXT NOT NULL DEFAULT '',
    workspace_id   TEXT NOT NULL DEFAULT '',
    datasource_id  TEXT NOT NULL DEFAULT '',
    table_name     TEXT NOT NULL,
    -- 表注释冗余在列行上：当前读模型是"列 + 所属表"的扁平结构（方案 §5.14-R2 要求入库）；
    -- 将来若引入独立的 table_info 表，此列降级为快照，保留以兼容既有读路径。
    table_comment  TEXT NOT NULL DEFAULT '',
    column_name    TEXT NOT NULL,
    column_comment TEXT NOT NULL DEFAULT '',
    data_type      TEXT NOT NULL DEFAULT '',
    embedding      vector({{vector_dim}}),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- P0-2 幂等重建的冲突目标：同一源同一表同一列只能有一行
    CONSTRAINT uq_nl2sql_column
        UNIQUE (tenant_id, workspace_id, datasource_id, table_name, column_name)
);
COMMENT ON TABLE nl2sql_column_info IS '列级元知识（表/列注释+类型+向量）；按 (tenant,workspace,datasource,table,column) 唯一';

-- ---------------------------------------------------------------------------
-- 2. 指标元知识：MetricRepository 向量召回 / save_metric 写入 / list_metrics 读取
--    代码读到的列：metric_name, metric_desc, metric_expr, embedding
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_metric_info (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT '',
    workspace_id  TEXT NOT NULL DEFAULT '',
    datasource_id TEXT NOT NULL DEFAULT '',
    metric_name   TEXT NOT NULL,
    metric_desc   TEXT NOT NULL DEFAULT '',
    -- 指标表达式（如 SUM(amount)）；只做语义提示，不直接拼进 SQL
    metric_expr   TEXT NOT NULL DEFAULT '',
    embedding     vector({{vector_dim}}),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_nl2sql_metric
        UNIQUE (tenant_id, workspace_id, datasource_id, metric_name)
);
COMMENT ON TABLE nl2sql_metric_info IS '指标口径元知识（名称/描述/表达式+向量）；P0-1 实装时必须同时写 embedding（当前无写入方，见 N14）';

-- ---------------------------------------------------------------------------
-- 3. 取值字典：ValueRepository 全文+向量召回 / save_value 写入
--    代码读到的列：column_name, value, value_desc, embedding, value_tsvector
--
--    value_tsvector 的生成方式是 B1 的落点（方案 §5.16 第 5 条）：
--    只从 search_text 生成，而 search_text 由构建方写入**同一套 Python 分词**后的
--    空格拼接 token。这样写入侧与查询侧（build_tsquery）单源，中英文都走 `simple`
--    配置的空格切分，不依赖任何 PG 中文词典扩展。
--    ⚠️ 构建方不写 search_text ⇒ 该行 tsvector 为空 ⇒ 全文路召不到（不是 bug，是契约）。
--    P0-7 定档后本表退役（取值改只读探针），故不为此表规划额外的长期治理。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_value_info (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT '',
    workspace_id  TEXT NOT NULL DEFAULT '',
    datasource_id TEXT NOT NULL DEFAULT '',
    column_name   TEXT NOT NULL,
    value         TEXT NOT NULL,
    value_desc    TEXT NOT NULL DEFAULT '',
    -- 由构建方写入：分词后以单空格拼接（例："北京  exhib 展览 中心"）
    search_text   TEXT NOT NULL DEFAULT '',
    value_tsvector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(search_text, ''))) STORED,
    embedding     vector({{vector_dim}}),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 自然键；value 若为超长自由文本可能撞 btree 单行 2704 字节上限（当前取值多为码表/地名，可接受）
    CONSTRAINT uq_nl2sql_value
        UNIQUE (tenant_id, workspace_id, datasource_id, column_name, value)
);
COMMENT ON TABLE nl2sql_value_info IS '取值字典（码表/地名/状态值）；tsvector 只从 search_text 生成，构建方负责写入分词结果';

-- ---------------------------------------------------------------------------
-- 4. 表间关系：§5.14-R2 规划中，代码当前零引用
--    用途：让 LLM 不再"猜 JOIN"；同名不同义（exhibitor_id）靠声明消歧
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_relation_info (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT '',
    workspace_id  TEXT NOT NULL DEFAULT '',
    datasource_id TEXT NOT NULL DEFAULT '',
    left_table    TEXT NOT NULL,
    left_column   TEXT NOT NULL,
    right_table   TEXT NOT NULL,
    right_column  TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'many_to_one'
        CHECK (relation_type IN ('many_to_one', 'one_to_one', 'one_to_many')),
    note          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_nl2sql_relation
        UNIQUE (tenant_id, workspace_id, datasource_id, left_table, left_column, right_table, right_column)
);
COMMENT ON TABLE nl2sql_relation_info IS '表间关系声明（§5.14-R2）；relation_type 是未来类型化属性的种子槽位，勿写死为无类型字符串';

-- ---------------------------------------------------------------------------
-- 5. 别名/同义词：§5.14-R1 规划中，代码当前零引用
--    P0-5 的"别名精确匹配"主路落在这张表（ts 全文只做兜底）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nl2sql_alias_info (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT '',
    workspace_id  TEXT NOT NULL DEFAULT '',
    datasource_id TEXT NOT NULL DEFAULT '',
    target_kind   TEXT NOT NULL CHECK (target_kind IN ('table', 'column', 'metric')),
    target_name   TEXT NOT NULL,
    alias         TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'machine')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_nl2sql_alias
        UNIQUE (tenant_id, workspace_id, datasource_id, target_kind, target_name, alias)
);
COMMENT ON TABLE nl2sql_alias_info IS '别名/同义词（§5.14-R1）：GMV→销售额 这类口语变体的声明载体；source 区分人工与机提，机提未确认前不应参与召回';

-- ---------------------------------------------------------------------------
-- 6. 索引
--    ANN：查询用 <=>（cosine distance），算子类必须是 vector_cosine_ops。
--    HNSW 需 pgvector >= 0.5；旧版本自动回退 ivfflat；两者都失败则只告警不中断
--    （向量召回退化为顺序扫描，仍可工作，但 P95 会随行数增长）。
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_nl2sql_column_embedding
        ON nl2sql_column_info USING hnsw (embedding vector_cosine_ops);
EXCEPTION WHEN OTHERS THEN
    BEGIN
        CREATE INDEX IF NOT EXISTS idx_nl2sql_column_embedding
            ON nl2sql_column_info USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        RAISE WARNING 'column_info: hnsw 不可用（pgvector < 0.5?），已回退 ivfflat';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'column_info: ANN 索引创建失败（%），向量召回将顺序扫描', SQLERRM;
    END;
END $$;

DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_nl2sql_metric_embedding
        ON nl2sql_metric_info USING hnsw (embedding vector_cosine_ops);
EXCEPTION WHEN OTHERS THEN
    BEGIN
        CREATE INDEX IF NOT EXISTS idx_nl2sql_metric_embedding
            ON nl2sql_metric_info USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        RAISE WARNING 'metric_info: hnsw 不可用（pgvector < 0.5?），已回退 ivfflat';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'metric_info: ANN 索引创建失败（%），向量召回将顺序扫描', SQLERRM;
    END;
END $$;

DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_nl2sql_value_embedding
        ON nl2sql_value_info USING hnsw (embedding vector_cosine_ops);
EXCEPTION WHEN OTHERS THEN
    BEGIN
        CREATE INDEX IF NOT EXISTS idx_nl2sql_value_embedding
            ON nl2sql_value_info USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        RAISE WARNING 'value_info: hnsw 不可用（pgvector < 0.5?），已回退 ivfflat';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'value_info: ANN 索引创建失败（%），向量召回将顺序扫描', SQLERRM;
    END;
END $$;

-- 全文路（build_tsquery → to_tsquery('simple', ...)）
CREATE INDEX IF NOT EXISTS idx_nl2sql_value_tsv
    ON nl2sql_value_info USING gin (value_tsvector);

-- 别名精确匹配：lower(alias) 等值 / LIKE 前缀
CREATE INDEX IF NOT EXISTS idx_nl2sql_alias_lower
    ON nl2sql_alias_info (lower(alias));

-- 关系召回：按左表或右表取某张表的所有关系
CREATE INDEX IF NOT EXISTS idx_nl2sql_relation_left
    ON nl2sql_relation_info (datasource_id, left_table);
CREATE INDEX IF NOT EXISTS idx_nl2sql_relation_right
    ON nl2sql_relation_info (datasource_id, right_table);
