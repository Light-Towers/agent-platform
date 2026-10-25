-- nl2sql-service 元知识库 schema v5：value_info 加 table_name + tokenizer（#117，2026-10-19）
-- 生成参考：docs/plans/plan-review-debt-cleanup-2026-10-19.md §3
--
-- 为什么需要这次迁移：`uq_nl2sql_value` 唯一键
-- (tenant_id, workspace_id, datasource_id, column_name, value) 不含 table_name ⇒
-- ① 同名列（orders.status vs venues.status）写第二个即撞约束，构建直接失败；
-- ② 行内无 table_name ⇒ 撞了也无法回溯所属表。同时 search_text 无分词器版本
-- 标记 ⇒ 换 tokenizer（bigram→jieba）后既有 search_text/tsvector 静默失效，
-- 召回率悄悄降而无人知晓（R5 后半）。
--
-- 纪律同 001-004：幂等（IF NOT EXISTS / 约束状态判定）、不回改旧文件、无数据
-- 迁移（存量行 table_name='' 与旧键同形，键变宽只会更宽松，不破坏存量）、
-- 无 DROP 列（down 文件除外）。
-- 应用方式同 001：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"

ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS table_name TEXT NOT NULL DEFAULT '';
ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS tokenizer TEXT NOT NULL DEFAULT '';

-- 换唯一键：不能只判"约束存在与否"——旧键同名 uq_nl2sql_value，存在性判断会
-- 把"已装旧键的库"误判为已迁移。按实际键列集合判定，不符才换（幂等）。
DO $$
DECLARE
    key_cols text;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conname = 'uq_nl2sql_value' AND c.contype = 'u';
    -- 目标键按 attname 排序的期望形态
    IF key_cols IS DISTINCT FROM 'column_name,datasource_id,table_name,tenant_id,value,workspace_id' THEN
        EXECUTE 'ALTER TABLE nl2sql_value_info DROP CONSTRAINT IF EXISTS uq_nl2sql_value';
        EXECUTE 'ALTER TABLE nl2sql_value_info ADD CONSTRAINT uq_nl2sql_value '
                'UNIQUE (tenant_id, workspace_id, datasource_id, table_name, column_name, value)';
    END IF;
END $$;

COMMENT ON COLUMN nl2sql_value_info.table_name IS '所属表名（#117：同名列跨表共存与回溯；空 = 旧配置/未标记）';
COMMENT ON COLUMN nl2sql_value_info.tokenizer IS 'search_text 的分词器标识（#117：换 tokenizer 后旧行可识别；空 = 未标记的旧数据）';

INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '5')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
