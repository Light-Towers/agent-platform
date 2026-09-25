-- v2: 为 chunks 表添加 workspace_id 列（隔离优化 G）
-- 幂等：新库由 baseline 建表时已含此列，此处为 no-op。

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks (workspace_id);
