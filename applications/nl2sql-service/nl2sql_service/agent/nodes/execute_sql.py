"""execute_sql 节点：只读执行。

连接级 default_transaction_read_only=on，与 app/sql/guard.py 语义一致。

2026-10-18 审计（方案 S-3）：此前 `str(exc)` 原样回显客户端，表/列存在性、
权限拒绝等可被当作探测 oracle。现改为**对外分类消息、详情只进日志与
`error_detail`**（后者供执行期纠错回路使用，不随响应体返回）。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext

logger = get_logger(__name__)

# 顺序敏感：先判可改写类（超时）、再判权限、最后判对象不存在
_ERROR_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("timeout", "canceling statement", "statement timeout", "query cancelled"), "查询超时：数据量或计算量超出时限"),
    (("permission denied", "insufficient privilege", "must be owner"), "查询被拒绝：当前账号无权访问相关数据"),
    (("does not exist", "undefined column", "undefined table", "syntax error"), "查询失败：表、字段或语法不正确"),
    (("could not connect", "connection refused", "server closed", "connection failed"), "查询失败：数据源连接不可用"),
)
_GENERIC_ERROR = "查询执行失败"
_UNRECOVERABLE = {_GENERIC_ERROR}


def classify_error(exc: BaseException) -> str:
    """把 DB 异常映射成对外可读的分类消息（详情不外泄）。"""
    text = str(exc).lower()
    for needles, message in _ERROR_RULES:
        if any(needle in text for needle in needles):
            return message
    return _GENERIC_ERROR


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
    except Exception as exc:  # noqa: BLE001 - 驱动异常类型不可穷举，按消息分类
        logger.exception("SQL execution failed")
        return {
            "result": None,
            "error": classify_error(exc),
            "error_detail": str(exc),
        }
