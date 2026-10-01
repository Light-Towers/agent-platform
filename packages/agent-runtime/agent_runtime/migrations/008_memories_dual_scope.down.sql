-- v8 rollback: restore the single-column layout (user_id carries the scope key).
-- Idempotent (IF EXISTS). Data-safety note: user-profile rows (scope='user')
-- written after v8 are DELETED by this rollback -- restore from backup if this
-- migration must be re-applied later. Workspace rows are preserved by copying
-- workspace_id back into user_id only for workspace-scoped rows.

UPDATE memories SET user_id = workspace_id
    WHERE scope = 'workspace' AND workspace_id IS NOT NULL;
DELETE FROM memories WHERE scope = 'user';

DROP INDEX IF EXISTS idx_memories_scope;
DROP INDEX IF EXISTS idx_memories_user;

ALTER TABLE memories DROP COLUMN IF EXISTS workspace_id;
ALTER TABLE memories DROP COLUMN IF EXISTS scope;
