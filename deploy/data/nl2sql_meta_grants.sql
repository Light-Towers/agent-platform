-- nl2sql 元知识库（nl2sql_meta）的库内权限 + vector 扩展在位校验。
-- 由 deploy/k8s/35-nl2sql-dbsql-job.yaml 以 **META_DB_DSN**（即服务将来使用的元库角色）
-- 连接执行——用 CURRENT_USER 而不是硬编码角色名， Secret 里那个 user 就是唯一真相。
--
-- 为什么单独一个文件：PG 的 GRANT ON SCHEMA 是**库内**语句，跨库要重连；
-- 与实例级的 nl2sql_dbsql.sql 分开，两个文件各自都能在 psql 里独立重放。
--
-- 幂等：全部语句可重复执行（GRANT 本身幂等），不含 DROP。

\set ON_ERROR_STOP on

-- 元库角色要能在 public 里建表与建索引：init_meta_schema 跑 001~006 的 DDL，
-- 在线摄入（/api/meta/ingest、平台 /sql/train 转发）要写行。
-- PG15 起新库的 public 已不再给 PUBLIC 建对象的权利（CREATE 收回，归 pg_database_owner），
-- 所以"是库 owner"不等于"能在 public 里建表"——这两条 GRANT 是把话说清楚，不是多余的。
GRANT USAGE, CREATE ON SCHEMA public TO CURRENT_USER;

-- vector 扩展：**本文件不建，只验**（2026-10-27 实测纠正）。
-- pgvector/pgvector:pg16 里 /usr/share/postgresql/16/extension/vector.control 的内容是
--   comment / default_version = '0.8.6' / module_pathname / relocatable = true
-- 没有 `trusted = true` ⇒ PG13+ 的"受信扩展可由 db owner 安装"这条**对它不成立**，
-- 建它需要超级用户。故建扩展的动作放在 35 Job 里用 $DATABASE_URL（集群超级用户）做，
-- 本文件只做 fail-closed 校验：不在位就直接中止（退出码 3），不让 001_meta_schema.up.sql 里那句
-- `CREATE EXTENSION IF NOT EXISTS vector` 以在线身份报 permission denied——
-- 那个报错指向"迁移文件坏了"，而真因是权限，排障成本高一截。
-- （用 RAISE EXCEPTION 不用 \quit：psql 16 实测 `\quit 2` 的参数被忽略且以 0 退出，会把 fail-closed 写成假绿。）
SELECT (SELECT count(*) FROM pg_extension WHERE extname = 'vector') = 0 AS missing \gset vec_
\if :vec_missing
\echo 'FATAL: vector 扩展不在位。它不是 trusted 扩展，须由超级用户先建（见 35 Job 第 2 步）'
DO $$ BEGIN RAISE EXCEPTION 'fail-closed: nl2sql_meta 里 vector 扩展不在位'; END $$;
\endif

SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

\echo 'OK: nl2sql_meta 库内权限已收敛，vector 扩展在位（读数见上）'
