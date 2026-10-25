-- v14a 回滚：workspaces 回到 (tenant_id, id) PK，摘 org/owner/visibility 列。
-- 注意：owner_user_id 删除丢属主登记（可由注册流程重建）；org_id 列删前须先
-- 还原 PK（列被 PK 引用不能直接 DROP）。幂等：列集判等后恢复 PK。

DO $$
DECLARE
    key_cols text;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY a.attname) INTO key_cols
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'workspaces'::regclass AND c.contype = 'p';
    IF key_cols IS DISTINCT FROM 'id,tenant_id' THEN
        EXECUTE 'ALTER TABLE workspaces DROP CONSTRAINT workspaces_pkey';
        EXECUTE 'ALTER TABLE workspaces ADD PRIMARY KEY (tenant_id, id)';
    END IF;
END $$;

ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS uq_workspaces_tenant_id_id;
ALTER TABLE workspaces DROP COLUMN IF EXISTS visibility;
ALTER TABLE workspaces DROP COLUMN IF EXISTS owner_user_id;
ALTER TABLE workspaces DROP COLUMN IF EXISTS org_id;
