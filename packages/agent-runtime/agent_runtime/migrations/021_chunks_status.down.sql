-- v21 down: 撤销 chunks.status 列
ALTER TABLE chunks DROP COLUMN IF EXISTS status;
