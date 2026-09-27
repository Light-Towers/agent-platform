-- v9 rollback: remove the corpus-derived ownership claims inserted by 009.
-- workspaces rows are additive claims (auto re-derivable on next reference via
-- resolve_workspace), so dropping them loses no business data. Deletes exactly
-- the (tenant_id, workspace_id) pairs still present in the corpus/memories
-- sources; any runtime re-registration of the same key is re-created on demand.

DELETE FROM workspaces
WHERE (tenant_id, id) IN (
    SELECT DISTINCT tenant_id, workspace_id FROM chunks      WHERE workspace_id IS NOT NULL AND workspace_id <> ''
    UNION SELECT DISTINCT tenant_id, workspace_id FROM sql_ddl     WHERE workspace_id IS NOT NULL AND workspace_id <> ''
    UNION SELECT DISTINCT tenant_id, workspace_id FROM sql_docs    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
    UNION SELECT DISTINCT tenant_id, workspace_id FROM sql_examples WHERE workspace_id IS NOT NULL AND workspace_id <> ''
    UNION SELECT DISTINCT tenant_id, workspace_id FROM memories    WHERE workspace_id IS NOT NULL AND workspace_id <> ''
);
