-- v7: workspaces ownership table (ADR-0006 D4 plan A, plan T10 / W2).
-- Proves which tenant a workspace belongs to. Workspace ids are namespaced per
-- tenant: the same raw id under two tenants yields two independent rows
-- (composite PK), so cross-tenant name collision is physically impossible.
-- First reference auto-registers under the calling tenant.

CREATE TABLE IF NOT EXISTS workspaces (
    tenant_id   TEXT NOT NULL,
    id          TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS idx_workspaces_id ON workspaces (id);
