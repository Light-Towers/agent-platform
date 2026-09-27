-- v7 rollback: drop the workspaces ownership table added by 007.
-- Idempotent (IF EXISTS). Ownership registration is derived data (auto-rebuilt
-- on first reference after re-applying 007), so dropping it loses no business rows.

DROP TABLE IF EXISTS workspaces;
