-- v20: chunks 表加 knowledge_id 列（多知识库文档检索，方案 plan-knowledge-base-model-2026-11-17）
--
-- 背景：文档检索统一到 DocumentStore 协议后，pgvector 后端要支持「按知识库收窄检索」
-- （knowledge_id 空 = 全部库）。chunks 表此前只有 tenant_id/workspace_id 两级范围，
-- knowledge_id 只存在于 KS 侧的 Milvus 集合，pgvector 侧无从过滤。
--
-- 语义约定：'' （空串）= 未归属知识库的存量文档 / 检索时不按 knowledge_id 过滤。
-- 用空串而不是 NULL：与 workspace_id 同款（v2/v6 先例），避免 IS NULL 判式渗进热路径。
--
-- 幂等：ADD COLUMN IF NOT EXISTS；旧行回填 ''（不归属任何知识库，行为与加列前一致）。
-- 不回改已应用文件（checksum 钉死）。

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS knowledge_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_chunks_knowledge
    ON chunks (tenant_id, workspace_id, knowledge_id);
