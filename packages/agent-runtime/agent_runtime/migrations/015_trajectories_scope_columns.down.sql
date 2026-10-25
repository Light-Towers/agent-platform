-- v15 回滚：摘 trajectories 三列（tenant_id/org_id/user_id）。
-- 注意：删除丢这三列上已写入的归属数据（轨迹回放/计费归因将回到无租户态）。
-- 幂等（DROP COLUMN IF EXISTS）。

DROP INDEX IF EXISTS idx_trajectories_tenant;
ALTER TABLE trajectories DROP COLUMN IF EXISTS user_id;
ALTER TABLE trajectories DROP COLUMN IF EXISTS org_id;
ALTER TABLE trajectories DROP COLUMN IF EXISTS tenant_id;
