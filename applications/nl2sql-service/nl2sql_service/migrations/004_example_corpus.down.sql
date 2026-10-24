-- nl2sql-service 元知识库 schema 回滚（v4 → v3）：删 nl2sql_example_info
-- 用途：仅开发/测试环境的清理，生产不执行。数据不可恢复。
-- 顺序：只撤 v4 建的表；v3/v2/v1 的回滚见 003/002/001 的 .down.sql。

DROP TABLE IF EXISTS nl2sql_example_info;

UPDATE nl2sql_schema_meta SET value = '3', updated_at = now() WHERE key = 'schema_version';
