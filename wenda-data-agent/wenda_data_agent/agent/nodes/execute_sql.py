"""execute_sql 节点：只读执行。

连接级 default_transaction_read_only=on，与 app/sql/guard.py 语义一致。
"""

from typing import Any

from agent_core.logging import get_logger

from wenda_data_agent.agent.context import DataAgentContext

logger = get_logger(__name__)


async def execute_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    error = state.get("error", "")
    ctx: DataAgentContext | None = state.get("context")
    if error:
        return {"result": None, "error": error}
    if not sql:
        return {"result": None, "error": "空 SQL"}
    if ctx is None or ctx.dw_repository is None:
        return {"result": None, "error": "数据仓库未连接"}

    try:
        result = await ctx.dw_repository.execute_readonly(sql)
        return {"result": result, "error": ""}
    except Exception as exc:
        logger.exception("SQL execution failed")
        return {"result": None, "error": str(exc)}
