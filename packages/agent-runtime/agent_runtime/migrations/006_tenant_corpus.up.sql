-- v6: corpus tables gain tenant_id as the security boundary (ADR-0006 D1, plan T9 / W1).
-- workspace_id stays an ownership predicate; every read/write must pair
-- (tenant_id, workspace_id). Existing rows are backfilled into the 'default'
-- bucket (single-tenant deployments keep reading them; real tenants never read
-- the default bucket -- no transitional cross-tenant reads, same semantics as v5).

-- 存量库升级路径补列（2026-09-30 R6 真集群复验拓出）：v2 只给 chunks 加了 workspace_id，
-- sql_ddl/sql_docs/sql_examples 在旧基线建表时无此列、增量链从未补 → 本文件复合索引必崩
-- （UndefinedColumn）。新库由 baseline 自带此列，下列 ALTER 对其为 no-op；DEFAULT '' 与
-- 001_baseline 现行定义对齐。幂等。
ALTER TABLE sql_ddl      ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '';
ALTER TABLE sql_docs     ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '';
ALTER TABLE sql_examples ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '';

ALTER TABLE chunks       ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_ddl      ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_docs     ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_examples ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_chunks_tenant       ON chunks        (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_ddl_tenant      ON sql_ddl       (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_docs_tenant     ON sql_docs      (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_examples_tenant ON sql_examples  (tenant_id, workspace_id);
