-- v3: memories 表扩展 memory_type / importance（长期记忆质量升级 H）
-- 幂等：新库由 baseline 建表时已含此列。

ALTER TABLE memories ADD COLUMN IF NOT EXISTS memory_type TEXT NOT NULL DEFAULT 'semantic';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS importance FLOAT NOT NULL DEFAULT 0.5;
CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories (user_id, memory_type);
