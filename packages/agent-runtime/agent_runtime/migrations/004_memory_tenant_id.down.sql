-- v4 rollback: 移除 memories.tenant_id 列与复合索引（回到 v3 无租户列状态）。
-- 与 up 对称：up 用 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，
-- down 用 DROP IF EXISTS，可安全重复执行。列内数据随列丢弃（回滚即放弃租户隔离维度）。
-- 注意：需先回滚 v5（其 ALTER COLUMN ... SET DEFAULT 依赖本列存在）。

DROP INDEX IF EXISTS idx_memories_tenant;
ALTER TABLE memories DROP COLUMN IF EXISTS tenant_id;
