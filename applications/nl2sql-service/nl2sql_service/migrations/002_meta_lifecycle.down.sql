-- nl2sql-service 元知识库 schema 回滚（v2 → v1）
-- 用途：仅开发/测试环境的清理，生产不执行。数据不可恢复。
-- 顺序：先删 v2 的三张新表；v1 的回滚见 001_meta_schema.down.sql。

DROP TABLE IF EXISTS nl2sql_table_stats;
DROP TABLE IF EXISTS nl2sql_query_trace;
DROP TABLE IF EXISTS nl2sql_session_state;

-- 版本标记回落 v1（表已不在，标记留着会误导 status 读数）
UPDATE nl2sql_schema_meta SET value = '1', updated_at = now() WHERE key = 'schema_version';
