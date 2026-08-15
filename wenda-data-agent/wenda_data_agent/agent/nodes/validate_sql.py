"""validate_sql 节点：复用 agent_core.sql.guard 白名单守卫。"""

from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.guard import validate_sql as _validate

logger = get_logger(__name__)


async def validate_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    max_rows = state.get("sql_max_rows", 1000)

    ok, reason, normalized = _validate(sql, "postgres", max_rows)
    if not ok:
        logger.warning("SQL validation failed: %s", reason)
        return {"sql_valid": False, "error": reason, "sql": sql}
    return {"sql_valid": True, "sql": normalized, "error": ""}
