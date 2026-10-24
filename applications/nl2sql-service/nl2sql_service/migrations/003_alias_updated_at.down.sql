-- nl2sql-service 元知识库 schema 回滚（v3 → v2）：删 alias_info.updated_at
-- 用途：仅开发/测试环境的清理，生产不执行。数据不可恢复。
-- 顺序：只撤 v3 补的列；v2/v1 的回滚见 002/001 的 .down.sql。

ALTER TABLE nl2sql_alias_info DROP COLUMN IF EXISTS updated_at;

UPDATE nl2sql_schema_meta SET value = '2', updated_at = now() WHERE key = 'schema_version';
