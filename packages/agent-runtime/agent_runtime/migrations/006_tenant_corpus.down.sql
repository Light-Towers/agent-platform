-- v6 rollback: drop tenant_id columns and composite indexes added by 006.
-- Idempotent (IF EXISTS). Data written with an explicit tenant before rollback is
-- collapsed back into the column default, mirroring the v5 down policy
-- (schema rollback only; no destructive data rewrite).

DROP INDEX IF EXISTS idx_chunks_tenant;
DROP INDEX IF EXISTS idx_sql_ddl_tenant;
DROP INDEX IF EXISTS idx_sql_docs_tenant;
DROP INDEX IF EXISTS idx_sql_examples_tenant;

ALTER TABLE chunks       DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE sql_ddl      DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE sql_docs     DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE sql_examples DROP COLUMN IF EXISTS tenant_id;
