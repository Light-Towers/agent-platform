-- nl2sql-service 元知识库 schema 回滚（v1 → 空库）
-- 用途：仅开发/测试环境的清理，生产不执行。
-- 注意：不 DROP EXTENSION vector —— 同库可能还有其他表在用。
-- 数据不可恢复；执行前确认 DSN 指向的是可丢弃的库。

DROP TABLE IF EXISTS nl2sql_alias_info;
DROP TABLE IF EXISTS nl2sql_relation_info;
DROP TABLE IF EXISTS nl2sql_value_info;
DROP TABLE IF EXISTS nl2sql_metric_info;
DROP TABLE IF EXISTS nl2sql_column_info;
DROP TABLE IF EXISTS nl2sql_schema_meta;
