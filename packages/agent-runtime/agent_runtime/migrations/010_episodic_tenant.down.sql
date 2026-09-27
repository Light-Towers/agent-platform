-- v10 rollback: drop tenant_id columns/indexes and restore procedural's global
-- (name, version) primary key. Idempotent (IF [NOT]/EXISTS).
--
-- Note: restoring the non-namespaced PK can fail if, while v10 was active, two
-- tenants wrote the same (name, version). That is expected -- a rollback to the
-- pre-isolation schema cannot preserve cross-tenant rows that the isolation was
-- added to separate. Delete one side's rows first if the re-key fails.

DROP INDEX IF EXISTS idx_episodic_tenant_imp;
DROP INDEX IF EXISTS idx_episodic_tenant_created;
ALTER TABLE episodic_memories DROP COLUMN IF EXISTS tenant_id;

DROP INDEX IF EXISTS idx_procedural_tenant_name;
ALTER TABLE procedural_memories DROP CONSTRAINT IF EXISTS procedural_memories_pkey;
ALTER TABLE procedural_memories ADD PRIMARY KEY (name, version);
ALTER TABLE procedural_memories DROP COLUMN IF EXISTS tenant_id;
