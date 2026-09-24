-- v2 rollback: 移除 chunks.workspace_id

DROP INDEX IF EXISTS idx_chunks_workspace;
ALTER TABLE chunks DROP COLUMN IF EXISTS workspace_id;
