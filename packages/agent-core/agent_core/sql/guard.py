# -*- coding: utf-8 -*-
"""SQL 白名单守卫：sqlglot 解析校验，只放行单条只读 SELECT。

规则：
1. 只允许单条语句，禁止分号堆叠；
2. 语句类型必须是 SELECT（WITH 开头的 CTE 由 sqlglot 归一为 Select）；
3. 禁止 DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/GRANT 等节点出现（含子查询内）；
4. 缺失 LIMIT 时强制追加 LIMIT max_rows，已有时校验不超过上限；
5. 禁止危险函数调用（`pg_sleep` 家族、`dblink`、`lo_import/lo_export`、
   `pg_read_file` 家族、`pg_terminate_backend`、`set_config`、MySQL 的
   `sleep`/`benchmark`）——它们是合法 SELECT，语句类型白名单挡不住，
   但能在只读连接上制造阻塞或改会话参数。schema 限定名（`pg_catalog.pg_sleep`）
   由 sqlglot 归一为裸函数名后同样命中。

框架无关：sqlglot 为可选 extra ``sql``，未安装时 import 抛 ImportError。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

FORBIDDEN_NODES = (
    exp.Drop,
    exp.Delete,
    exp.Update,
    exp.Insert,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Set,
    exp.Into,  # SELECT ... INTO
)

#: 合法 SELECT 但能阻塞连接 / 读写服务端文件 / 改会话参数的函数（2026-10-18 S-11）。
#: 覆盖 PG 与 MySQL 两侧最常用的 DoS 与越权面；不含聚合/字符串等正常函数。
FORBIDDEN_FUNCTIONS = frozenset(
    {
        # PostgreSQL：阻塞
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        # PostgreSQL：外部连接（可绕过只读语义）
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "dblink_disconnect",
        # PostgreSQL：服务端文件
        "lo_import",
        "lo_export",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        # PostgreSQL：运维面
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "set_config",  # 可把 statement_timeout 改回 0
        # MySQL：阻塞
        "sleep",
        "benchmark",
    }
)


def _function_name(node: exp.Func) -> str:
    """取函数名（小写、去 schema 前缀）；专用节点回落类名。"""
    if isinstance(node, exp.Anonymous):
        raw = node.this
        name = raw if isinstance(raw, str) else getattr(raw, "name", "")
        return str(name).rsplit(".", 1)[-1].lower()
    return type(node).__name__.lower()


def validate_sql(sql: str, dialect: str, max_rows: int) -> tuple[bool, str, str]:
    """返回 (是否放行, 原因, 规整后的 SQL)。"""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        return False, "空 SQL", sql
    if ";" in cleaned:
        return False, "禁止多语句", sql

    try:
        statements = [s for s in sqlglot.parse(cleaned, read=dialect) if s is not None]
    except sqlglot.errors.ParseError as exc:
        return False, f"SQL 解析失败: {exc}", sql
    if len(statements) != 1:
        return False, "只允许单条语句", sql

    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        return False, "只允许 SELECT 查询", sql
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return False, f"包含禁止的 SQL 操作: {type(node).__name__}", sql
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in FORBIDDEN_FUNCTIONS:
                return False, f"包含禁止的函数调用: {name}", sql

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        limit_expr = limit.expression
        if isinstance(limit_expr, exp.Literal) and limit_expr.is_int:
            if int(limit_expr.this) > max_rows:
                stmt = stmt.limit(max_rows)
        else:
            return False, "LIMIT 必须是整数字面量", sql

    return True, "ok", stmt.sql(dialect=dialect)


__all__ = ["FORBIDDEN_FUNCTIONS", "FORBIDDEN_NODES", "validate_sql"]
