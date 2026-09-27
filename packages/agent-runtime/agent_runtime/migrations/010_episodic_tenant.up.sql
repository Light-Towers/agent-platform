-- v10: episodic_memories / procedural_memories gain tenant_id as the security
-- boundary (plan-memory-hardening T1 / ADR-0006 G1, D3). Multi-tenant confirmed,
-- so both tables' previously tenant-less recall/list were cross-tenant visible.
-- Same semantics as v5/v6: existing rows backfill into 'default'; no transitional
-- cross-tenant reads (real tenants never see the default bucket).

-- --- episodic_memories ---
ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
UPDATE episodic_memories SET tenant_id = 'default' WHERE tenant_id = '';
ALTER TABLE episodic_memories ALTER COLUMN tenant_id SET DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_episodic_tenant_imp ON episodic_memories (tenant_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_tenant_created ON episodic_memories (tenant_id, created_at DESC);

-- --- procedural_memories ---
-- Skills are derived from tenant execution traces (ProceduralExtractor uses
-- task_summary) and can collide across tenants; ADR-0006 D3 fixes them as
-- "intra-tenant shared, cross-tenant isolated" -> namespace the primary key by
-- tenant_id so two tenants keep independent (name, version) rows.
ALTER TABLE procedural_memories ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
UPDATE procedural_memories SET tenant_id = 'default' WHERE tenant_id = '';
ALTER TABLE procedural_memories ALTER COLUMN tenant_id SET DEFAULT 'default';
-- Re-key PK (tenant_id, name, version). (name, version) uniqueness is a subset,
-- so no duplicate (tenant_id, name, version) can exist after the tenant column is added.
ALTER TABLE procedural_memories DROP CONSTRAINT IF EXISTS procedural_memories_pkey;
ALTER TABLE procedural_memories ADD PRIMARY KEY (tenant_id, name, version);
CREATE INDEX IF NOT EXISTS idx_procedural_tenant_name ON procedural_memories (tenant_id, name);
