-- v4: memories 表补 tenant_id 列（P1-5 多租户隔离 defense-in-depth）
-- 当前隔离靠 user_id 全局唯一；此列为未来跨租户 user_id 复用场景预留边界。

ALTER TABLE memories ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_memories_tenant ON memories (tenant_id, user_id);
