"""build_graph：异步 StateGraph 编排 12 节点 Text-to-SQL 管线。

extract_keywords → 并行召回 → merge → 并行过滤 → add_context → generate → validate → 条件边 → execute/correct
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from nl2sql_service.agent.nodes.add_extra_context import add_extra_context
from nl2sql_service.agent.nodes.answer import answer
from nl2sql_service.agent.nodes.correct_sql import correct_sql
from nl2sql_service.agent.nodes.execute_sql import execute_sql
from nl2sql_service.agent.nodes.extract_keywords import extract_keywords
from nl2sql_service.agent.nodes.filter_metric import filter_metric
from nl2sql_service.agent.nodes.filter_table import filter_table
from nl2sql_service.agent.nodes.generate_sql import generate_sql
from nl2sql_service.agent.nodes.merge_retrieved_info import merge_retrieved_info
from nl2sql_service.agent.nodes.recall_column import recall_column
from nl2sql_service.agent.nodes.recall_metric import recall_metric
from nl2sql_service.agent.nodes.recall_relation import recall_relation
from nl2sql_service.agent.nodes.recall_value import recall_value
from nl2sql_service.agent.nodes.triage_empty import triage_empty
from nl2sql_service.agent.nodes.validate_literals import validate_literals
from nl2sql_service.agent.nodes.validate_sql import validate_sql
from nl2sql_service.agent.state import DataAgentState


def _route_after_validate(state: dict[str, Any]) -> str:
    if state.get("sql_valid", False):
        return "validate_literals"
    if state.get("correct_count", 0) >= state.get("sql_max_correct_retries", 3):
        # 2026-10-18 审计（方案 §5.11-E2 补款）：达上限落错误终态，不再路由 execute_sql。
        # 旧路由把"未校验 SQL 不执行"寄托在 execute_sql 的 error 非空提前返回上，
        # 是隐式耦合——那边一旦改空就成真执行。
        return END
    return "correct_sql"


def _route_after_literals(state: dict[str, Any]) -> str:
    """字面量核验后路由（P0-8②）。

    确定性未命中 ⇒ 进 correct（换字面量正是模型擅长的）；未达上限才放行；
    达上限 ⇒ 错误终态（带未命中字面量收尾，不硬执行）。
    unknown（探不到）不设 error，直接放行——"探不到"≠"不存在"（C8）。
    """
    if not state.get("error"):
        return "execute_sql"
    if state.get("correct_count", 0) >= state.get("sql_max_correct_retries", 3):
        return END
    return "correct_sql"


def _route_after_execute(state: dict[str, Any]) -> str:
    """执行后路由（方案 §5.11-E2 图修正 + M0-4 answer 边）。

    成功 → 零结果分诊（P0-8③：0 行要区分"取值未匹配"与"真无数据"）；
    可纠正/可改写且 correct_count 未达上限 → correct_sql；
    不可纠正（fatal）或达上限 → 错误终态（END）。

    correct_count 与 validate 回路**共用同一个上限**（E4：总 LLM 调用数
    = sql_max_correct_retries + 固定开销，两个回路各计 3 次就没了闸）。
    """
    if not state.get("error"):
        return "triage_empty"
    if state.get("error_class") in ("correctable", "rewritable") and state.get(
        "correct_count", 0
    ) < state.get("sql_max_correct_retries", 3):
        return "correct_sql"
    return END


def _route_after_triage(state: dict[str, Any]) -> str:
    """零结果分诊后路由：判定"取值未匹配" ⇒ 允许重生成一次（P0-8③）。"""
    if not state.get("error"):
        return "answer"
    if state.get("correct_count", 0) >= state.get("sql_max_correct_retries", 3):
        return END
    return "correct_sql"


def build_graph():
    """构建并编译 12 节点 Text-to-SQL 管线图。"""
    graph = StateGraph(DataAgentState)

    graph.add_node("extract_keywords", extract_keywords)
    graph.add_node("recall_column", recall_column)
    graph.add_node("recall_metric", recall_metric)
    graph.add_node("recall_value", recall_value)
    graph.add_node("recall_relation", recall_relation)
    graph.add_node("merge_retrieved_info", merge_retrieved_info)
    graph.add_node("filter_table", filter_table)
    graph.add_node("filter_metric", filter_metric)
    graph.add_node("add_extra_context", add_extra_context)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("validate_literals", validate_literals)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("correct_sql", correct_sql)
    graph.add_node("triage_empty", triage_empty)
    graph.add_node("answer", answer)

    graph.add_edge(START, "extract_keywords")

    graph.add_edge("extract_keywords", "recall_column")
    graph.add_edge("extract_keywords", "recall_metric")
    graph.add_edge("extract_keywords", "recall_value")
    graph.add_edge("extract_keywords", "recall_relation")

    graph.add_edge("recall_column", "merge_retrieved_info")
    graph.add_edge("recall_metric", "merge_retrieved_info")
    graph.add_edge("recall_value", "merge_retrieved_info")
    graph.add_edge("recall_relation", "merge_retrieved_info")

    graph.add_edge("merge_retrieved_info", "filter_table")
    graph.add_edge("merge_retrieved_info", "filter_metric")

    graph.add_edge("filter_table", "add_extra_context")
    graph.add_edge("filter_metric", "add_extra_context")

    graph.add_edge("add_extra_context", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")

    graph.add_conditional_edges(
        "validate_sql",
        _route_after_validate,
        {"validate_literals": "validate_literals", "correct_sql": "correct_sql", END: END},
    )
    # 字面量核验（P0-8②）：确定性未命中进 correct，unknown 放行
    graph.add_conditional_edges(
        "validate_literals",
        _route_after_literals,
        {"execute_sql": "execute_sql", "correct_sql": "correct_sql", END: END},
    )
    graph.add_edge("correct_sql", "validate_sql")
    # 2026-10-18（方案 §5.11-E2）：execute_sql 从无条件边改条件边——
    # 执行期异常（correctable/rewritable）进 correct 回路，fatal/达上限
    # 直接错误终态；成功先过零结果分诊（P0-8③）再合成答案（M0-4）。
    graph.add_conditional_edges(
        "execute_sql",
        _route_after_execute,
        {"triage_empty": "triage_empty", "correct_sql": "correct_sql", END: END},
    )
    graph.add_conditional_edges(
        "triage_empty",
        _route_after_triage,
        {"answer": "answer", "correct_sql": "correct_sql", END: END},
    )
    graph.add_edge("answer", END)

    return graph.compile()
