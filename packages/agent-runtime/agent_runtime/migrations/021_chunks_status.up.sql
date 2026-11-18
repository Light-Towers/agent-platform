-- v21: chunks 表加 status 列（多知识库软删除，plan-kb-delete-and-management-2026-11-18 P2）
--
-- 背景：知识库删除语义选软删除（REVOKED），与 Milvus chunk 的 status 字段（v3 集合）
-- 对齐。pgvector 降级后端也要能屏蔽 REVOKED 切片，否则切到 pgvector 时软删除失效。
--
-- 语义：'active'（默认，有效）/ 'REVOKED'（软删除，检索排除）。
-- 用空串兼容存量：老行回填 'active'（行为与加列前一致，检索谓词 status != 'REVOKED' 仍召回）。
-- 幂等：ADD COLUMN IF NOT EXISTS；不回改已应用文件（checksum 钉死）。

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
