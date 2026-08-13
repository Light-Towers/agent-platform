"""validate_sql 节点：sqlglot 白名单守卫。

复用 app/sql/guard.py 安全语义：单条 SELECT + 禁止 DDL/DML + LIMIT 强制。
独立实现以保持 wenda-data-agent 包自洽。
"""

from typing import Any

import sqlglot
from agent_core.logging import get_logger
from sqlglot import exp

logger = get_logger(__name__)

_FORBIDDEN_NODES = (
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
    exp.Into,
)


async def validate_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    max_rows = state.get("sql_max_rows", 1000)

    ok, reason, normalized = _validate(sql, "postgres", max_rows)
    if not ok:
        logger.warning("SQL validation failed: %s", reason)
        return {"sql_valid": False, "error": reason, "sql": sql}
    return {"sql_valid": True, "sql": normalized, "error": ""}


def _validate(sql: str, dialect: str, max_rows: int) -> tuple[bool, str, str]:
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
        if isinstance(node, _FORBIDDEN_NODES):
            return False, f"包含禁止的 SQL 操作: {type(node).__name__}", sql
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
