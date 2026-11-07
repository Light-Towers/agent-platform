-- 业务样例数仓（nl2sql_dw）的 L1 权限：服务账号 nl2sql_dw_reader **只有 SELECT**。
-- 由 deploy/k8s/35-nl2sql-dbsql-job.yaml 在 fixture 之后执行（前置：表已存在，
-- `GRANT ... ON ALL TABLES` 对当时不存在的表不生效，未来的表靠最后一条默认权限）。
-- 以超级用户连接执行：`ALTER DEFAULT PRIVILEGES FOR ROLE nl2sql_dw_owner` 要求执行者
-- 是该角色成员或超级用户。
--
-- 这条防线为什么排在最前：三层纵深（见 applications/nl2sql-service/README.md 的
-- 「数据权限（三层纵深）」小节）里只有 L1 在数据库内生效，
-- 不依赖应用代码正确——应用侧 L2（表/列白名单）与 L3（结果掩码）一旦有 bug，L1 仍在。
-- 服务自身不建任何 DDL（ADR-0011 Q10a 裁定），所以它也不需要这里的任何写权限。
--
-- 边界要如实说，别把 L1 写成"列级隔离"：
--   * L1 是**只读**，不是列白名单——`SELECT phone FROM users` 在库侧是被允许的；
--     users.phone 的保护来自应用侧 L2 投影黑名单 + L3 结果掩码（清单里
--     SENSITIVE_COLUMNS=users.phone，见 deploy/k8s/30-nl2sql-service.yaml）。
--   * 要 DB 侧也拦得住，得建脱敏视图并把 reader 的 SELECT 收束到视图上——本部署**没有**建，
--     属已知残余，不在这里假装存在。
--
-- 幂等：GRANT/REVOKE 可重复执行，不含 DROP。

\set ON_ERROR_STOP on

-- 库级：收回 PUBLIC 的默认 CONNECT，只放行 reader（dw_owner 是 NOLOGIN 组角色，靠 SET ROLE 进入）。
REVOKE ALL ON DATABASE nl2sql_dw FROM PUBLIC;
GRANT CONNECT ON DATABASE nl2sql_dw TO nl2sql_dw_reader;

-- schema 级：USAGE 但不给 CREATE（PG15 起默认就没有，仍显式收回——
-- 万一有人在库里手工 `GRANT CREATE TO PUBLIC` 放过，重跑本 Job 会把它收回来）。
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM nl2sql_dw_reader;
GRANT USAGE ON SCHEMA public TO nl2sql_dw_reader;

-- 对象级：当前全部表/序列只读。序列不需要（只读路径不 nextval），故不授。
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_dw_reader;

-- 将来新增的表也自动只读给 reader（否则"重跑一次 fixture 加表"就出现一张没人授权、
-- 或授权走了写路径的表）。只对 nl2sql_dw_owner 后续创建的对象生效——正是 fixture 的所属角色。
ALTER DEFAULT PRIVILEGES FOR ROLE nl2sql_dw_owner IN SCHEMA public
    GRANT SELECT ON TABLES TO nl2sql_dw_reader;

-- 自查读数（打印出来，让"只有 SELECT"这件事在 Job 日志里可见而不是靠人记）：
-- has_table_privilege 的列级结果应当全是 t（SELECT），且写类权限全为 f。
SELECT
    c.relname AS table_name,
    has_table_privilege('nl2sql_dw_reader', c.oid, 'SELECT') AS can_select,
    has_table_privilege('nl2sql_dw_reader', c.oid, 'INSERT') AS can_insert,
    has_table_privilege('nl2sql_dw_reader', c.oid, 'UPDATE') AS can_update,
    has_table_privilege('nl2sql_dw_reader', c.oid, 'DELETE') AS can_delete,
    has_table_privilege('nl2sql_dw_reader', c.oid, 'TRUNCATE') AS can_truncate
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname;

\echo 'OK: nl2sql_dw_reader 已收敛为只读（上表 can_insert/update/delete/truncate 必须全为 f）'
