-- v6: corpus tables gain tenant_id as the security boundary (ADR-0006 D1, plan T9 / W1).
-- workspace_id stays an ownership predicate; every read/write must pair
-- (tenant_id, workspace_id). Existing rows are backfilled into the 'default'
-- bucket (single-tenant deployments keep reading them; real tenants never read
-- the default bucket -- no transitional cross-tenant reads, same semantics as v5).

ALTER TABLE chunks       ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_ddl      ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_docs     ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_examples ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_chunks_tenant       ON chunks        (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_ddl_tenant      ON sql_ddl       (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_docs_tenant     ON sql_docs      (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_examples_tenant ON sql_examples  (tenant_id, workspace_id);
