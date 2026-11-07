-- nl2sql 问数数据面的**实例级** DDL：建两库、建角色、把口令与 DSN 对齐。
-- 由 deploy/k8s/35-nl2sql-dbsql-job.yaml 以集群超级用户身份执行（幂等、可重跑）。
-- 库内权限不在本文件：PG 的 GRANT ON SCHEMA / ON TABLE 是库内对象，分别由
-- nl2sql_meta_grants.sql / nl2sql_dw_grants.sql 承担（同一个 Job 顺序执行）。
--
-- 三库三角色（ADR-0011 终态的数据面划分）：
--   agent_platform   平台库，本脚本不碰（10-postgres.yaml 的既有拓扑）
--   nl2sql_meta      元知识库（表/列/指标/值/关系/别名 + pgvector）。角色 = DSN 里的 user
--                    （约定名 nl2sql_meta）：LOGIN，是该库的 owner——在线路径要写它
--                    （/api/meta/ingest、平台 /sql/train 转发过来的摄入）
--   nl2sql_dw        业务样例数仓，两个角色：
--                    nl2sql_dw_owner  NOLOGIN 组角色，只决定"建出来的对象归谁"；
--                                     服务从不以它连接（fixture 由 Job 用 PGOPTIONS 切到它）
--                    nl2sql_dw_reader LOGIN，**只有 GRANT SELECT**——三层纵深的 L1
--                    （见 applications/nl2sql-service/README.md 的「数据权限（三层纵深）」小节）
--
-- 口令的唯一来源是 Secret 里那两个 DSN：本脚本从 META_DB_DSN / DW_DB_DSN 解析 user/password，
-- 角色不存在就建、存在就把口令同步成 DSN 里的值 ⇒ 重跑即收敛，且仓内不存在第二份口令材料。
-- （若另设 *_PASSWORD 键，轮换就会漏改其中一处，线上表现是"服务连不上库"——最难查的形状。）
--
-- 三条 fail-closed 断言，任一不成立就中止（退出码 3，非零）。用 RAISE EXCEPTION 而不是
-- \quit 是有实测原因的（2026-10-27 ap-iso-pg / psql 16）：`\quit 2` 的参数被忽略
-- （`warning: \quit: extra argument "2" ignored`）且进程以 **0** 退出 ⇒ FATAL 打印了、
-- Job 却判成功，这是最危险的一类假绿。故断言统一走 DO 块抛错 + 文件顶的 ON_ERROR_STOP。
--   1) DSN 解析不出 user/password；
--   2) DSN 的 user/库名 ≠ 本清单固定的 (nl2sql_meta, nl2sql_meta) / (nl2sql_dw_reader, nl2sql_dw)。
--      角色名与库名同时出现在清单和 Secret 两侧，不对账就会出现"建了个没人用的角色"；
--   3) 口令含 `%`。本脚本取 DSN 的**字面**口令建角色，而 libpq 会先做 URL 解码，
--      带百分号的口令会建出一个与服务端期待值不同的角色口令——宁可不干，不干错。
--      这类口令走运维手工建角色。⚠ 本仓**没有**成文这一条操作（旧写法指向
--      deploy/k8s/README.md §6.3，那一节现在是登录面签名密钥，与这里无关），别改这里。
--
-- 幂等边界：已存在的库/角色只做"同步口令 + 补权限"，不 DROP、不改属主。
-- 判据（跑完后应看到的读数，见 docs/operations/nl2sql-release-checklist.md §3 步 6）：
-- `\du` 里 nl2sql_dw_reader 是
-- `Cannot be assigned by SET ROLE`（NOLOGIN 组角色只有 owner）、Attributes 无 superuser。

\set ON_ERROR_STOP on

\getenv ap_meta_dsn META_DB_DSN
\getenv ap_dw_dsn DW_DB_DSN

-- 形态：postgres(ql)://user:password@host[:port]/db?args
-- 口令段用 ([^@]*)：DSN 里唯一必现的 @ 是 userinfo 与 host 的分界，取第一个 @ 之前
-- 冒号后的整段，才能容忍口令里的 `:/#` 等字符（`@` 本身不允许，见断言 1 的形态要求）。
-- 每个表达式都包 coalesce：regexp_match 不匹配返回 NULL，而 `\gset` **跳过 NULL 列**，
-- 变量就不存在，后面 `:'ap_meta_user'` 展开成裸冒号 ⇒ `syntax error at or near ":"`（实测）。
-- 那种失败虽然也非零，但报错指向"SQL 写错了"，而真因是 DSN 形态不对——在生成侧就归一成 ''。
SELECT
    coalesce((regexp_match(:'ap_meta_dsn', '^postgres(?:ql)?://([^:]*):([^@]*)@'))[1], '') AS meta_user,
    coalesce((regexp_match(:'ap_meta_dsn', '^postgres(?:ql)?://([^:]*):([^@]*)@'))[2], '') AS meta_password,
    coalesce((regexp_match(:'ap_meta_dsn', '@[^/?]+/([^?]*)'))[1], '') AS meta_database,
    coalesce((regexp_match(:'ap_dw_dsn', '^postgres(?:ql)?://([^:]*):([^@]*)@'))[1], '') AS dw_user,
    coalesce((regexp_match(:'ap_dw_dsn', '^postgres(?:ql)?://([^:]*):([^@]*)@'))[2], '') AS dw_password,
    coalesce((regexp_match(:'ap_dw_dsn', '@[^/?]+/([^?]*)'))[1], '') AS dw_database
\gset ap_

SELECT (
    :'ap_meta_user' = '' OR :'ap_meta_password' = ''
    OR :'ap_dw_user' = '' OR :'ap_dw_password' = ''
) AS bad \gset parse_
\if :parse_bad
\echo 'FATAL: META_DB_DSN / DW_DB_DSN 解析不出 user:password，需 postgresql://user:password@host:5432/db 形态'
DO $$ BEGIN RAISE EXCEPTION 'fail-closed: DSN 解析不出 user:password（断言 1）'; END $$;
\endif

SELECT (:'ap_meta_user' <> 'nl2sql_meta' OR :'ap_meta_database' <> 'nl2sql_meta'
        OR :'ap_dw_user' <> 'nl2sql_dw_reader' OR :'ap_dw_database' <> 'nl2sql_dw') AS bad \gset dbname_
\if :dbname_bad
\echo 'FATAL: DSN 的 user/库名与本清单固定的角色名不匹配（nl2sql_meta@nl2sql_meta / nl2sql_dw_reader@nl2sql_dw）'
DO $$ BEGIN RAISE EXCEPTION 'fail-closed: DSN 的 user/库名与清单角色名不匹配（断言 2）'; END $$;
\endif

SELECT (position('%' IN :'ap_meta_password') > 0 OR position('%' IN :'ap_dw_password') > 0) AS bad \gset pct_
\if :pct_bad
\echo 'FATAL: DSN 口令含 %（URL 编码歧义，见本文件头部断言 3）；请换口令或走运维手工建角色'
DO $$ BEGIN RAISE EXCEPTION 'fail-closed: DSN 口令含百分号（断言 3）'; END $$;
\endif

-- ---------------------------------------------------------------------------
-- 1. 角色
--    PG 没有 CREATE ROLE IF NOT EXISTS，故用 \gexec 条件执行；角色名是清单固定值（上面
--    断言 2 已把 DSN 的 user 取齐），只有口令经 format('%L') 引用，不靠拼接抗特殊字符。
-- ---------------------------------------------------------------------------
SELECT format('CREATE ROLE nl2sql_meta LOGIN PASSWORD %L', :'ap_meta_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_meta')\gexec

SELECT format('CREATE ROLE nl2sql_dw_reader LOGIN PASSWORD %L', :'ap_dw_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_dw_reader')\gexec

-- 口令同步：角色已存在也要与 DSN 对齐（轮换后重跑本 Job 即收敛，不必进库手改）。
-- 带 rolcanlogin 条件：若同名角色被建成 NOLOGIN，那是拓扑冲突，不该由本脚本静默改成可登录。
SELECT format('ALTER ROLE nl2sql_meta LOGIN PASSWORD %L', :'ap_meta_password')
WHERE EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_meta' AND rolcanlogin
)\gexec

SELECT format('ALTER ROLE nl2sql_dw_reader LOGIN PASSWORD %L', :'ap_dw_password')
WHERE EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_dw_reader' AND rolcanlogin
)\gexec

SELECT 'CREATE ROLE nl2sql_dw_owner NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_dw_owner')\gexec

-- ---------------------------------------------------------------------------
-- 2. 两个库（CREATE DATABASE 不能在事务块里 ⇒ 逐条自动提交，脚本不包 BEGIN）
-- ---------------------------------------------------------------------------
SELECT 'CREATE DATABASE nl2sql_meta OWNER nl2sql_meta'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'nl2sql_meta')\gexec

SELECT 'CREATE DATABASE nl2sql_dw OWNER nl2sql_dw_owner'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'nl2sql_dw')\gexec

\echo 'OK: 角色与两库已收敛（库内权限见 nl2sql_meta_grants.sql / nl2sql_dw_grants.sql）'
