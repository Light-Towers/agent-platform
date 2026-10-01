-- v9: backfill workspaces ownership rows for already-referenced (tenant_id,
-- workspace_id) pairs so pre-T10 corpus/memories have ownership claims before
-- real tenants start sharing common workspace_id strings. Runs after 006 (corpus
-- tenant_id) / 007 (workspaces) / 008 (memories.workspace_id), all of which
-- apply first by version order. Idempotent (ON CONFLICT DO NOTHING); safe to
-- re-run. Empty/NULL workspace_id buckets are skipped (no bogus claims).

INSERT INTO workspaces (tenant_id, id)
SELECT DISTINCT tenant_id, workspace_id FROM chunks
    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
ON CONFLICT (tenant_id, id) DO NOTHING;

INSERT INTO workspaces (tenant_id, id)
SELECT DISTINCT tenant_id, workspace_id FROM sql_ddl
    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
ON CONFLICT (tenant_id, id) DO NOTHING;

INSERT INTO workspaces (tenant_id, id)
SELECT DISTINCT tenant_id, workspace_id FROM sql_docs
    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
ON CONFLICT (tenant_id, id) DO NOTHING;

INSERT INTO workspaces (tenant_id, id)
SELECT DISTINCT tenant_id, workspace_id FROM sql_examples
    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
ON CONFLICT (tenant_id, id) DO NOTHING;

INSERT INTO workspaces (tenant_id, id)
SELECT DISTINCT tenant_id, workspace_id FROM memories
    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
ON CONFLICT (tenant_id, id) DO NOTHING;
