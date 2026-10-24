-- v12: receipt generation fencing（V3 缺口 1 的两类未覆盖 durable write）
--
-- 背景：fencing 边界此前只覆盖 3/5 类 durable write——checkpoint
-- （execution_checkpoints.generation，见 planner/durability_pg.py 的 save() WHERE 子句）、
-- execution status（execution_status.generation，见 execution_state_pg.py）、scheduler
-- ownership（execution_leases.generation，takeover 时 +1）。剩下两类**回执**没有任何
-- generation 列，因此 zombie writer（lease 被接管后仍在跑的旧 owner）能写下假回执：
--
--   1. awaitable_tasks：外部任务回执（submission_receipt / completion_receipt）。
--      旧 owner 覆盖 state/receipt 会让恢复路径按错误的"外部真实状态"决策。
--   2. side_effects：副作用回执（effect_key 幂等去重）。旧 owner 抢先插入一条
--      effect_key，会让新 owner 的 has() 判为"已落地"从而**跳过本该执行的副作用**。
--
-- 两列都可空、无默认值 ⇒ 存量行保持 NULL，读写路径按 NULL 退回"不 fence"语义
-- （与 execution_checkpoints.generation 在 v11 的处置同构：NULL = 未知来源，不参与比较）。
-- 新建库跑完整链 001..012 同样得到这两列 ⇒ 新库与升级库形状一致，不分叉。
--
-- 幂等：两条 ALTER 均带 IF NOT EXISTS，重复执行 no-op。
-- 刻意**不改** 001_baseline.up.sql：已应用的迁移文件被 schema_migrations.checksum 钉住，
-- 改动会让存量库启动时报 checksum mismatch（runner 的既有判据）。

ALTER TABLE awaitable_tasks ADD COLUMN IF NOT EXISTS generation BIGINT;
ALTER TABLE side_effects    ADD COLUMN IF NOT EXISTS generation BIGINT;
