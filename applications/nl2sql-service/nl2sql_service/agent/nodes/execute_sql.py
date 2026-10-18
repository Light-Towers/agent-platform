"""execute_sql 节点：只读执行 + 执行期异常三分类。

连接级 default_transaction_read_only=on，与 app/sql/guard.py 语义一致。

2026-10-18 审计（方案 S-3）：此前 `str(exc)` 原样回显客户端，表/列存在性、
权限拒绝等可被当作探测 oracle。现改为**对外分类消息、详情只进日志与
`error_detail`**（后者供执行期纠错回路使用，不随响应体返回）。

2026-10-18（方案 §5.11-E2 实装）：执行期异常此前直接 END，模型永远不知道
SQL 在真实库上错了。现输出 `error_class` 三分类，由图决定是否进 correct：
- correctable：列/表名不存在、语法错、类型不匹配——错误信息可机器识别，
  改 SQL 可能解决；
- rewritable：超时取消一类——进 correct 但带改写方向；
- fatal：权限拒绝、连接失败——**不喂模型**（喂 3 轮也改不出来，还扩大
  注入面），直接错误终态。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext

logger = get_logger(__name__)

#: error_detail 截断上限：原文只进 prompt/日志，防超长堆栈撑爆上下文
_ERROR_DETAIL_MAX_CHARS = 500

#: 顺序敏感：先判可改写类（超时）、再判权限、最后判对象不存在。
#: 三元组 = (错误文本 needle, 对外分类消息, error_class)。
_ERROR_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("timeout", "canceling statement", "statement timeout", "query cancelled"),
        "查询超时：数据量或计算量超出时限",
        "rewritable",
    ),
    (
        ("permission denied", "insufficient privilege", "must be owner"),
        "查询被拒绝：当前账号无权访问相关数据",
        "fatal",
    ),
    (
        (
            "does not exist",
            "undefined column",
            "undefined table",
            "syntax error",
            # 类型不匹配（方案 §5.11-E2 归 correctable）：PG 的原话是
            # invalid input syntax / invalid text representation 一族
            "invalid input syntax",
            "invalid text representation",
            "datatype mismatch",
            "cannot be cast",
            "type mismatch",
        ),
        "查询失败：表、字段或语法不正确",
        "correctable",
    ),
    (
        ("could not connect", "connection refused", "server closed", "connection failed"),
        "查询失败：数据源连接不可用",
        "fatal",
    ),
)
_GENERIC_ERROR = "查询执行失败"
#: 未识别错误按 fatal：不可分类的原文进 prompt 只扩大注入面（S-7），
#: 现网出现高频未知错时的正确动作是补 needle，不是放宽到"都喂模型"。
_GENERIC_CLASS = "fatal"


def classify_error(exc: BaseException) -> str:
    """把 DB 异常映射成对外可读的分类消息（详情不外泄）。"""
    return _classify(exc)[0]


def classify_error_class(exc: BaseException) -> str:
    """把 DB 异常映射到 {correctable, rewritable, fatal}（图路由用）。"""
    return _classify(exc)[1]


def _classify(exc: BaseException) -> tuple[str, str]:
    text = str(exc).lower()
    for needles, message, error_class in _ERROR_RULES:
        if any(needle in text for needle in needles):
            return message, error_class
    return _GENERIC_ERROR, _GENERIC_CLASS


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
        # 成功必须清空三类错误字段：state 跨轮累积，上一轮的失败痕迹
        # 留在 error_class 里会让路由又把成功轮送进 correct。
        return {"result": result, "error": "", "error_detail": "", "error_class": ""}
    except Exception as exc:  # noqa: BLE001 - 驱动异常类型不可穷举，按消息分类
        logger.exception("SQL execution failed")
        message, error_class = _classify(exc)
        detail = str(exc)[:_ERROR_DETAIL_MAX_CHARS]
        # 已尝试序列（§5.11 feedback 契约③）：没有它，模型会把同一处错改三遍
        attempted = list(state.get("attempted_sql") or [])
        attempted.append({"sql": sql, "error": detail})
        return {
            "result": None,
            "error": message,
            "error_detail": detail,
            "error_class": error_class,
            "attempted_sql": attempted,
        }
