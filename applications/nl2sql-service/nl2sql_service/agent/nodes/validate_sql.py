"""validate_sql 节点：复用 agent_core.sql.guard 白名单守卫 + 表/列级策略（§5.9 L2）。"""

from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.guard import SqlPolicy, validate_sql_with_policy

logger = get_logger(__name__)


def _build_policy(state: dict[str, Any]) -> SqlPolicy | None:
    """从 state 构表/列级策略；两项都空 = 无策略（回退纯语句级，老部署一致）。"""
    allowed = {t.lower() for t in (state.get("allowed_tables") or []) if t}
    sensitive = {c.lower() for c in (state.get("sensitive_columns") or []) if c}
    if not allowed and not sensitive:
        return None
    return SqlPolicy(
        allowed_tables=frozenset(allowed) if allowed else None,
        sensitive_columns=frozenset(sensitive) if sensitive else None,
    )


async def validate_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    max_rows = state.get("sql_max_rows", 1000)
    # 方言按数据源分支（P1-4）：sqlglot 解析 + LIMIT 规整都随 dialect——
    # 同一句 SQL 在 MySQL / PG 上的解析边界不同，硬编码 postgres 会把
    # MySQL 专有写法误判。缺省 postgres 保持老部署逐字节一致。
    dialect = state.get("dialect") or "postgres"
    policy = _build_policy(state)
    ok, reason, normalized = validate_sql_with_policy(sql, dialect, max_rows, policy)
    if not ok:
        logger.warning("SQL validation failed: %s", reason)
        return {"sql_valid": False, "error": reason, "sql": sql}
    return {"sql_valid": True, "sql": normalized, "error": ""}
