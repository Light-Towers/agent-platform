-- v5: tenant_id 成为 memories 的实际隔离谓词。
-- v4 只增加列，本迁移把历史空值归入 default，并固定默认值，避免新写入落回空租户。
UPDATE memories SET tenant_id = 'default' WHERE tenant_id = '';
ALTER TABLE memories ALTER COLUMN tenant_id SET DEFAULT 'default';
