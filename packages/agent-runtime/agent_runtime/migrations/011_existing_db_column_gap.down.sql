-- v11 rollback: drop the columns that 011 re-added to legacy databases.
-- Idempotent (IF EXISTS). Schema-only rollback — no destructive data rewrite,
-- mirroring the v5/v6 down policy.
--
-- WARNING: on a database that was created by the *current* baseline these columns
-- are not "extra" — dropping them re-breaks /query (lease acquire INSERTs the
-- generation column) and the tenant-scoped semantic cache. Roll back 011 only
-- together with a baseline that predates those columns.

ALTER TABLE execution_leases      DROP COLUMN IF EXISTS generation;
ALTER TABLE execution_checkpoints DROP COLUMN IF EXISTS generation;
ALTER TABLE execution_checkpoints DROP COLUMN IF EXISTS state_schema_version;
ALTER TABLE semantic_cache        DROP COLUMN IF EXISTS tenant_id;
