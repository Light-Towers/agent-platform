-- v8: memories dual scope (plan T13 / W3, user decision: cross-workspace user
-- profile must exist). The user_id column historically carried workspace_id
-- (TD-13); this migration moves those values into a dedicated workspace_id
-- column, marks the rows scope='workspace', and frees user_id for real users.
--
-- Pre-flight check on real multi-tenant deployments (plan §5.1): confirm no
-- genuine user ids were written into the user_id column before applying; if any
-- exist, resolve ownership first. The 'default' placeholder keeps legacy rows
-- readable through the workspace path ((tenant, scope, workspace_id) predicate).

ALTER TABLE memories ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'workspace';

UPDATE memories SET workspace_id = user_id WHERE workspace_id IS NULL;
UPDATE memories SET user_id = 'default' WHERE scope = 'workspace' AND user_id <> 'default';

CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (tenant_id, scope, workspace_id);
CREATE INDEX IF NOT EXISTS idx_memories_user  ON memories (tenant_id, scope, user_id);
