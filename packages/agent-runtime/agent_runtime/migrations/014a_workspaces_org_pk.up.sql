-- v14a: workspaces 升级三级归属（D7/D8，plan §9.5/§9.14-⑤；014b 的 SET NOT NULL 等 T4 后半）
--
-- 内容：org_id 加列 + backfill（同值域 = tenant_id）+ NOT NULL + PK (tenant_id,id)→(org_id,id)
--       + owner_user_id（可空，009 backfill 的存量无主行留 NULL = 过渡态）+ visibility
--       （默认 'private'，D7：workspace 严格属用户不跨用户共享；'org' 公共空间须 admin
--       显式注册（D18 闸门），本迁移只建列不灌公共行）。
--
-- 注意：tenant_id 列保留（谓词零改动），PK 换用 org_id 列（值域同、语义升级）。
-- 幂等：全部 IF NOT EXISTS / 条件判断；PK 重建按 pg_constraint 列集判等（005/006 配方）。
-- 纪律：不回改 007（checksum 钉住）。

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS org_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

UPDATE workspaces SET org_id = tenant_id WHERE org_id IS NULL;
ALTER TABLE workspaces ALTER COLUMN org_id SET NOT NULL;

DO $$
DECLARE
    key_cols text;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'workspaces'::regclass AND c.contype = 'p';
    IF key_cols IS DISTINCT FROM 'id,org_id' THEN
        EXECUTE 'ALTER TABLE workspaces DROP CONSTRAINT workspaces_pkey';
        EXECUTE 'ALTER TABLE workspaces ADD PRIMARY KEY (org_id, id)';
    END IF;
END $$;

-- 同值域下 (tenant_id, id) 与新 PK 等价；保留 UNIQUE 使 register_workspace 的
-- ON CONFLICT (tenant_id, id) 在 007-013（旧 PK）与 014a 后（本约束）两阶段均合法
-- （渐进部署窗口内不因换 PK 报 42P10 no_unique_constraint）。
DO $$
DECLARE
    key_cols text;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'workspaces'::regclass
      AND c.contype = 'u' AND c.conname = 'uq_workspaces_tenant_id_id';
    IF key_cols IS DISTINCT FROM 'id,tenant_id' THEN
        EXECUTE 'ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS uq_workspaces_tenant_id_id';
        EXECUTE 'ALTER TABLE workspaces ADD CONSTRAINT uq_workspaces_tenant_id_id '
                'UNIQUE (tenant_id, id)';
    END IF;
END $$;

COMMENT ON COLUMN workspaces.org_id IS '所属企业（= 租户断言值，013 同值域决策；014a backfill 自 tenant_id）';
COMMENT ON COLUMN workspaces.owner_user_id IS '属主用户（D18：自动注册绑服务端断言 user；NULL = 存量无主过渡态/公共空间）';
COMMENT ON COLUMN workspaces.visibility IS 'private=严格属主（D7 默认）；org=企业共享（须 admin 显式注册，D18 闸门）';
