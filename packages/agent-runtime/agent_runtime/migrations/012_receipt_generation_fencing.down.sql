-- v12 回滚：摘掉两类回执的 generation 列。
--
-- 注意：回滚后 fencing 能力随之消失（写入退回"无 generation"语义），但**不丢业务数据**
-- ——两列只存 lease generation，不是回执内容本身。
-- DROP COLUMN IF EXISTS 幂等。

ALTER TABLE awaitable_tasks DROP COLUMN IF EXISTS generation;
ALTER TABLE side_effects    DROP COLUMN IF EXISTS generation;
