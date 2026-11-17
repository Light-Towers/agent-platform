-- v20 down: 撤销 chunks.knowledge_id（列 + 复合索引）
DROP INDEX IF EXISTS idx_chunks_knowledge;
ALTER TABLE chunks DROP COLUMN IF EXISTS knowledge_id;
