-- 005 down：撤销 value_info 的 table_name + tokenizer（#117）
-- 恢复旧唯一键（去掉 table_name）后删两列。注意：若迁移后已写入同名列跨表
-- 数据（orders.status 与 venues.status 同值），恢复旧键会失败——那是数据层
-- 事实，down 前须先清理，本文件不静默删数据。
ALTER TABLE nl2sql_value_info DROP CONSTRAINT IF EXISTS uq_nl2sql_value;
ALTER TABLE nl2sql_value_info ADD CONSTRAINT uq_nl2sql_value
    UNIQUE (tenant_id, workspace_id, datasource_id, column_name, value);
ALTER TABLE nl2sql_value_info DROP COLUMN IF EXISTS tokenizer;
ALTER TABLE nl2sql_value_info DROP COLUMN IF EXISTS table_name;

INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '4')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
