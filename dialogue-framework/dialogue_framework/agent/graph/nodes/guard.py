"""guard 节点：SQL 守卫 + 输出守卫 + 安全过滤。

复用 agent_core.sql.guard.validate_sql 进行 SQL 校验（sqlglot AST），
保留 SQL marker 预检（避免对非 SQL 文本解析）和敏感内容过滤。

拒绝时设置 guard_passed=False，条件边回退 policy 重新策略。
"""

from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.guard import validate_sql

logger = get_logger(__name__)

_SENSITIVE_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
)

_SQL_MARKERS = ("select ", "with ", "insert ", "update ", "delete ", "drop ", "create ", "alter ", "truncate ")


async def guard(state: dict[str, Any]) -> dict[str, Any]:
    result = state.get("action_result", "")
    action_type = state.get("action_type", "")

    sql_ok, sql_reason = _check_sql(result, action_type)
    if not sql_ok:
        logger.warning("guard rejected (sql): %s", sql_reason)
        return {"guard_passed": False, "guard_reason": sql_reason}

    filtered = _filter_sensitive(result)
    if filtered != result:
        logger.info("guard filtered sensitive content")

    return {"guard_passed": True, "action_result": filtered, "guard_reason": "ok"}


def _check_sql(text: str, action_type: str) -> tuple[bool, str]:
    lowered = text.lower()
    if not any(marker in lowered for marker in _SQL_MARKERS):
        return True, "ok"
    ok, reason, _sql = validate_sql(text, dialect="postgres", max_rows=10000)
    return ok, reason


def _filter_sensitive(text: str) -> str:
    lowered = text.lower()
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in lowered:
            return "[内容已过滤：包含敏感信息]"
    return text
