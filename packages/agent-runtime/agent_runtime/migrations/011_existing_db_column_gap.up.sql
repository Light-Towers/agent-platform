-- v11: 存量库列缺口补齐（2026-10-10 演示版第 0 天真集群实跑拓出，方案
-- docs/plans/plan-schema-drift-existing-db-gap-2026-10-10.md）。
--
-- 根因与 v6 同族、但形态更隐蔽：集群库是**被 stamp 过的存量库**——schema_migrations 里
-- 1..10 的 applied_at 完全相同（2026-09-30 02:38:43.941711+00），说明走的是 runner
-- _try_baseline_stamp() 的「只记版本号、不执行 DDL」路径。此后 baseline 的
-- CREATE TABLE IF NOT EXISTS 对已存在的旧形状表是**永久 no-op**，而增量链 002..010 又从未
-- 覆盖这几列 ⇒ 缺口**不会随重建镜像收敛**（v6 注释登记的 sql_* 缺 workspace_id 是同类先例，
-- 判据同一条：新库由现行 baseline 自带该列，所以本地/CI 永不暴露）。
--
-- 实测缺列（information_schema 直查 + 与 migrations 声明面取集合差，全库差集 = 4 列）：
--   execution_leases.generation                                 → /query 主链路必崩（下列 1）
--   execution_checkpoints.generation / state_schema_version     → checkpoint 落库与 generation fencing 失效
--   semantic_cache.tenant_id                                    → 被 cache_lookup 的 except 吞成永久 miss
--
-- 1) 集群实错原文（未鉴权 POST /query 的 SSE error 事件）：
--      column "generation" of relation "execution_leases" does not exist
--   触发点：PlannerRuntime.execution() **每次进入执行边界都 acquire 租约**
--     （planner/protocol.py:522 → planner/durability_pg.py:219 的 INSERT 列含 generation），
--   默认 deterministic planner 的全部 /query 请求因此失败。
--
-- 列定义逐一对齐 001_baseline 现行声明（type / nullability / default 全部照抄），
-- 本迁移只做「让存量库等于 baseline 声明的形状」这一件事：不新增索引、不改默认值口径、
-- 不顺手做租户语义收敛（semantic_cache.tenant_id 在 baseline 里是 ''，此处即为 ''；
-- 若要按 v5/v6/v10 收敛到 'default' 桶，属独立迁移，混进来会让新建库与升级库再度分叉）。
-- 新建库上四条 ALTER 全部命中 IF NOT EXISTS ⇒ no-op。幂等。

ALTER TABLE execution_leases      ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 1;
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS generation BIGINT;
ALTER TABLE execution_checkpoints ADD COLUMN IF NOT EXISTS state_schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE semantic_cache        ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT '';
