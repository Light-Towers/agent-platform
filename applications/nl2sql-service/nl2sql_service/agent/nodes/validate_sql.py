"""validate_sql 节点：复用 agent_core.sql.guard 白名单守卫。"""

from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.guard import validate_sql as _validate

logger = get_logger(__name__)


async def validate_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    max_rows = state.get("sql_max_rows", 1000)
    # 方言按数据源分支（P1-4）：sqlglot 解析 + LIMIT 规整都随 dialect——
    # 同一句 SQL 在 MySQL / PG 上的解析边界不同，硬编码 postgres 会把
    # MySQL 专有写法误判。缺省 postgres 保持老部署逐字节一致。
    dialect = state.get("dialect") or "postgres"
    ok, reason, normalized = _validate(sql, dialect, max_rows)
    if not ok:
        logger.warning("SQL validation failed: %s", reason)
        return {"sql_valid": False, "error": reason, "sql": sql}
    return {"sql_valid": True, "sql": normalized, "error": ""}
