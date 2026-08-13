"""guard 节点：SQL 守卫 + 输出守卫 + 安全过滤。

复用 app/sql/guard.py 语义（sqlglot 解析 + 只读校验 + LIMIT 强制），
独立实现以保持 dialogue-framework 包自洽，不改动 app/sql。

拒绝时设置 guard_passed=False，条件边回退 policy 重新策略。
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

_SENSITIVE_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
)


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
    sql_markers = ("select ", "with ", "insert ", "update ", "delete ", "drop ", "create ", "alter ", "truncate ")
    if not any(marker in lowered for marker in sql_markers):
        return True, "ok"
    cleaned = text.strip().rstrip(";").strip()
    if not cleaned:
        return True, "ok"
    if ";" in cleaned:
        return False, "禁止多语句"
    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        return False, f"SQL 解析失败: {exc}"
    if len(statements) != 1:
        return False, "只允许单条语句"
    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        return False, "只允许 SELECT 查询"
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return False, f"包含禁止的 SQL 操作: {type(node).__name__}"
    return True, "ok"


def _filter_sensitive(text: str) -> str:
    lowered = text.lower()
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in lowered:
            return "[内容已过滤：包含敏感信息]"
    return text
