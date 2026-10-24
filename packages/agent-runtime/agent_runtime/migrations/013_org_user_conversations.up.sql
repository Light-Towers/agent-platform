-- v13: 三级归属实体 organizations / users / conversations（D7/D9/D11，plan §9.5）
-- 依据：docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md（2026-10-23 拍板轮）
--
-- D7：租户 > 用户 > 工作空间三级；workspace 严格属用户。
-- D9：一人只属一个企业（users.org_id 直挂，不建 memberships），角色降为 is_admin。
-- D11 选项 C：旁置 conversations 归属表 + thread_id 转不透明 uuid（新会话起），
--   不动 checkpoints（表由 saver.setup() 外部建、INSERT 由 LangGraph 持有）。
--
-- 值域决策（org_id = tenant_id 同值域，D0 可逆）：D9 单企业语义下 org 是租户的
-- 企业化升级，organizations.id 直接使用现有 tenant 断言值（''/'default'/JWT claim），
-- workspaces.org_id 由 014 backfill 自 tenant_id——所有 WHERE tenant_id 谓词零改动。
-- 将来引入"一 org 多 tenant"时另立迁移重映射（纯 expand）。
--
-- conversations.user_id 先可空（§9.8 中间态口径：014b 前 read 断言只到 org 级，
-- 不得宣传"会话按人隔离已具备"）；014b（T4 后半，A5 claim 绑定后）SET NOT NULL。
-- 存量 tenant-<t> 线程不回填（§9.8-①：归属永久无从重建，不进新列表、不再可写）。
--
-- 幂等：IF NOT EXISTS 全覆盖；不回改已应用文件（checksum 钉住）。

CREATE TABLE IF NOT EXISTS organizations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- D9：org_id 直挂（一人一企业）；is_admin 是仅存的角色位（memberships/grants 已 D13 砍）
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL REFERENCES organizations(id),
    display_name TEXT NOT NULL DEFAULT '',
    is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_org ON users (org_id);

-- D11 选项 C：旁置归属表。归属断言点 = conversations 包装器（agent_runtime.conversations），
-- 写入为单语句 upsert（ON CONFLICT ... WHERE 归属匹配 RETURNING 1，0 行即拒绝，§9.6-5）。
CREATE TABLE IF NOT EXISTS conversations (
    thread_id      TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL REFERENCES organizations(id),
    -- 可空中间态：014b（T4 后半）SET NOT NULL，前置 = A5 JWT claim 绑定 + 写入点 user 可得
    user_id        TEXT,
    workspace_id   TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_org_user ON conversations (org_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_last_active ON conversations (last_active_at DESC);

-- 回填 organizations：现有租户断言值即企业 id（同值域决策，见头部注释）
INSERT INTO organizations (id)
SELECT DISTINCT tenant_id FROM workspaces WHERE tenant_id IS NOT NULL AND tenant_id <> ''
ON CONFLICT (id) DO NOTHING;
