-- nl2sql-service 元知识库 schema v6：7 处 UNIQUE 摘 workspace_id（D8 摘键留列，2026-10-23）
-- 依据：docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md §9.5/§9.14（用户拍板一）
--
-- 为什么摘：D8 拍板元知识（列/指标/取值/关系/别名/范例/表统计）全企业同一套，
-- 不随空间因人而异。workspace_id 留列作**首灌来源**溯源（upsert 键外、非 updatable
-- ⇒ 冲突更新永不覆盖，见 meta_repository._upsert 形态），不再参与唯一性。
--
-- 范围修正（§9.14-①）：session_state（002:33）**不摘**——它是会话数据非元知识，
-- 摘了会让多轮四元组全企业共享（状态互串，反向违反 D7 归属拍板）。
--
-- 为什么现在做（§9.5 纪律③）：今天所有行 workspace_id 同值 ⇒ 摘键零冲突；
-- 等不同空间各自导入过元知识后再摘，会撞"同键多版本"的人工裁决。
--
-- 前置查重纪律：摘键是变窄（005 的"变宽不破坏存量"不可照抄）——先按新键
-- GROUP BY 查重，有重复即 RAISE EXCEPTION 退出，**不许自选留存**。
--
-- 幂等纪律同 001-005：按 pg_constraint 实际列集合判等（001 的 UNIQUE 为匿名
-- 约束，不能按约束名判存在性）；不回改已应用文件；无数据迁移。
-- 应用方式同 001：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"

-- ---------------------------------------------------------------------------
-- 前置：按摘后新键查重，任何一表有重复即整体中止（不部分应用）
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    dup text;
BEGIN
    SELECT format('%s: %s 行', t.tbl, t.n) INTO dup
    FROM (
        SELECT 'nl2sql_column_info' AS tbl, count(*) AS n FROM (
            SELECT 1 FROM nl2sql_column_info
            GROUP BY tenant_id, datasource_id, table_name, column_name HAVING count(*) > 1) d
        UNION ALL
        SELECT 'nl2sql_metric_info', count(*) FROM (
            SELECT 1 FROM nl2sql_metric_info
            GROUP BY tenant_id, datasource_id, metric_name HAVING count(*) > 1) d
        UNION ALL
        SELECT 'nl2sql_value_info', count(*) FROM (
            SELECT 1 FROM nl2sql_value_info
            GROUP BY tenant_id, datasource_id, table_name, column_name, value HAVING count(*) > 1) d
        UNION ALL
        SELECT 'nl2sql_relation_info', count(*) FROM (
            SELECT 1 FROM nl2sql_relation_info
            GROUP BY tenant_id, datasource_id, left_table, left_column, right_table, right_column HAVING count(*) > 1) d
        UNION ALL
        SELECT 'nl2sql_alias_info', count(*) FROM (
            SELECT 1 FROM nl2sql_alias_info
            GROUP BY tenant_id, datasource_id, target_kind, target_name, alias HAVING count(*) > 1) d
        UNION ALL
        SELECT 'nl2sql_table_stats', count(*) FROM (
            SELECT 1 FROM nl2sql_table_stats
            GROUP BY tenant_id, datasource_id, table_name HAVING count(*) > 1) d
        UNION ALL
        SELECT 'nl2sql_example_info', count(*) FROM (
            SELECT 1 FROM nl2sql_example_info
            GROUP BY tenant_id, datasource_id, question HAVING count(*) > 1) d
    ) t
    WHERE t.n > 0
    LIMIT 1;
    IF dup IS NOT NULL THEN
        RAISE EXCEPTION '006 摘键前置查重失败：% 与新唯一键重复（同键多版本，须人工裁决后再迁移，不许自选留存）', dup;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 换键：按实际列集合判等（匿名约束不能按名判），不符才换。共 7 处。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    key_cols text;
BEGIN
    -- ① column_info
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_column_info'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'column_name,datasource_id,table_name,tenant_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_column_info DROP CONSTRAINT IF EXISTS uq_nl2sql_column';
        EXECUTE 'ALTER TABLE nl2sql_column_info ADD CONSTRAINT uq_nl2sql_column '
                'UNIQUE (tenant_id, datasource_id, table_name, column_name)';
    END IF;

    -- ② metric_info
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_metric_info'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'datasource_id,metric_name,tenant_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_metric_info DROP CONSTRAINT IF EXISTS uq_nl2sql_metric';
        EXECUTE 'ALTER TABLE nl2sql_metric_info ADD CONSTRAINT uq_nl2sql_metric '
                'UNIQUE (tenant_id, datasource_id, metric_name)';
    END IF;

    -- ③ value_info（现行键为 005 重建的六列）
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_value_info'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'column_name,datasource_id,table_name,tenant_id,value' THEN
        EXECUTE 'ALTER TABLE nl2sql_value_info DROP CONSTRAINT IF EXISTS uq_nl2sql_value';
        EXECUTE 'ALTER TABLE nl2sql_value_info ADD CONSTRAINT uq_nl2sql_value '
                'UNIQUE (tenant_id, datasource_id, table_name, column_name, value)';
    END IF;

    -- ④ relation_info
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_relation_info'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'datasource_id,left_column,left_table,right_column,right_table,tenant_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_relation_info DROP CONSTRAINT IF EXISTS uq_nl2sql_relation';
        EXECUTE 'ALTER TABLE nl2sql_relation_info ADD CONSTRAINT uq_nl2sql_relation '
                'UNIQUE (tenant_id, datasource_id, left_table, left_column, right_table, right_column)';
    END IF;

    -- ⑤ alias_info
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_alias_info'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'alias,datasource_id,target_kind,target_name,tenant_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_alias_info DROP CONSTRAINT IF EXISTS uq_nl2sql_alias';
        EXECUTE 'ALTER TABLE nl2sql_alias_info ADD CONSTRAINT uq_nl2sql_alias '
                'UNIQUE (tenant_id, datasource_id, target_kind, target_name, alias)';
    END IF;

    -- ⑥ table_stats
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_table_stats'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'datasource_id,table_name,tenant_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_table_stats DROP CONSTRAINT IF EXISTS uq_nl2sql_table_stats';
        EXECUTE 'ALTER TABLE nl2sql_table_stats ADD CONSTRAINT uq_nl2sql_table_stats '
                'UNIQUE (tenant_id, datasource_id, table_name)';
    END IF;

    -- ⑦ example_info（⚠️ 004 的文件名是 `004_example_corpus.up.sql` 而表名是
    -- `nl2sql_example_info`——本文件初版把文件名抄成了表名，真 PG 上 42P01 连带
    -- 回滚 001-005。引用他包迁移时以 `CREATE TABLE` 原文为准，不信文件名）
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'nl2sql_example_info'::regclass AND c.contype = 'u';
    IF key_cols IS DISTINCT FROM 'datasource_id,question,tenant_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_example_info DROP CONSTRAINT IF EXISTS uq_nl2sql_example';
        EXECUTE 'ALTER TABLE nl2sql_example_info ADD CONSTRAINT uq_nl2sql_example '
                'UNIQUE (tenant_id, datasource_id, question)';
    END IF;
END $$;

COMMENT ON COLUMN nl2sql_column_info.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';
COMMENT ON COLUMN nl2sql_metric_info.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';
COMMENT ON COLUMN nl2sql_value_info.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';
COMMENT ON COLUMN nl2sql_relation_info.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';
COMMENT ON COLUMN nl2sql_alias_info.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';
COMMENT ON COLUMN nl2sql_table_stats.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';
COMMENT ON COLUMN nl2sql_example_info.workspace_id IS '首灌来源空间（D8 摘键后仅溯源，不再参与唯一性）';

INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '6')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
