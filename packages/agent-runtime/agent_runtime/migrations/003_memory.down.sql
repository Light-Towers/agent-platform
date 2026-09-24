-- v3 rollback: 移除 memories.memory_type / importance

DROP INDEX IF EXISTS idx_memories_user_type;
ALTER TABLE memories DROP COLUMN IF EXISTS importance;
ALTER TABLE memories DROP COLUMN IF EXISTS memory_type;
