-- v15: trajectories 补隔离与归属列（G8，plan §9.5）
--
-- 缺口实锤（2026-10-23 施工时发现）：TrajectoryRecord.tenant_id 字段存在于
-- models.py:57 但 store_pg.save() 列清单不含它、001 DDL 也无该列 ⇒ 租户字段
-- 从未落库。本迁移一并补齐三列：
--   - tenant_id（隔离域，G8）
--   - org_id / user_id（归属计量，D7 三级）
-- 三列均可空、无默认（012 配方：NULL = 未知来源/存量行，新写入带值；
-- 与 execution_checkpoints.generation 在 v11 的处置同构）。
-- 新建库跑完整链 001..015 同样得到这三列 ⇒ 新库与升级库形状一致。
--
-- 幂等：IF NOT EXISTS；不回改 001/trajectories 建表段（checksum 钉住）。

ALTER TABLE trajectories ADD COLUMN IF NOT EXISTS tenant_id TEXT;
ALTER TABLE trajectories ADD COLUMN IF NOT EXISTS org_id TEXT;
ALTER TABLE trajectories ADD COLUMN IF NOT EXISTS user_id TEXT;

CREATE INDEX IF NOT EXISTS idx_trajectories_tenant ON trajectories (tenant_id);
