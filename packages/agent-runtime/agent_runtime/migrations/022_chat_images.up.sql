-- v22: chat_images 表（会话传图提问，plan-image-qa-fullstack-2026-11-23）
--
-- 用户在会话里上传的图片以 bytea 存共享 PG（agent_server 三副本无共享本地盘，不能存本地文件）。
-- ref 是不透明引用（chat-images/<tenant>/<session>/<uuid>.<ext> 语义的短标识），不含集群内 host，
-- 避免把 minio:9000 暴露给前端；/query 时后端按 ref 取字节转 data URI 喂 VL 模型。
-- 租户隔离：tenant_id 列 + ref 前缀双重约束；读取时服务端断言 tenant 与 ref 首段一致。

CREATE TABLE IF NOT EXISTS chat_images (
    ref           TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    content       BYTEA NOT NULL,
    content_type  TEXT NOT NULL,
    byte_size     INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- TTL 清理（CHAT_IMAGE_TTL_DAYS）按 created_at 扫；会话维度查询按 (tenant_id, session_id)。
CREATE INDEX IF NOT EXISTS idx_chat_images_tenant_session ON chat_images (tenant_id, session_id);
CREATE INDEX IF NOT EXISTS idx_chat_images_created_at ON chat_images (created_at);
