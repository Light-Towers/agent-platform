"""build_graph：异步 StateGraph 编排 12 节点 Text-to-SQL 管线。

extract_keywords → 并行召回 → merge → 并行过滤 → add_context → generate → validate → 条件边 → execute/correct
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from wenda_data_agent.agent.nodes.add_extra_context import add_extra_context
from wenda_data_agent.agent.nodes.correct_sql import correct_sql
from wenda_data_agent.agent.nodes.execute_sql import execute_sql
from wenda_data_agent.agent.nodes.extract_keywords import extract_keywords
from wenda_data_agent.agent.nodes.filter_metric import filter_metric
from wenda_data_agent.agent.nodes.filter_table import filter_table
from wenda_data_agent.agent.nodes.generate_sql import generate_sql
from wenda_data_agent.agent.nodes.merge_retrieved_info import merge_retrieved_info
from wenda_data_agent.agent.nodes.recall_column import recall_column
from wenda_data_agent.agent.nodes.recall_metric import recall_metric
from wenda_data_agent.agent.nodes.recall_value import recall_value
from wenda_data_agent.agent.nodes.validate_sql import validate_sql
from wenda_data_agent.agent.state import DataAgentState


def _route_after_validate(state: dict[str, Any]) -> str:
    if state.get("sql_valid", False):
        return "execute_sql"
    if state.get("correct_count", 0) >= state.get("sql_max_correct_retries", 3):
        return "execute_sql"
    return "correct_sql"


def build_graph():
    """构建并编译 12 节点 Text-to-SQL 管线图。"""
    graph = StateGraph(DataAgentState)

    graph.add_node("extract_keywords", extract_keywords)
    graph.add_node("recall_column", recall_column)
    graph.add_node("recall_metric", recall_metric)
    graph.add_node("recall_value", recall_value)
    graph.add_node("merge_retrieved_info", merge_retrieved_info)
    graph.add_node("filter_table", filter_table)
    graph.add_node("filter_metric", filter_metric)
    graph.add_node("add_extra_context", add_extra_context)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("correct_sql", correct_sql)

    graph.add_edge(START, "extract_keywords")

    graph.add_edge("extract_keywords", "recall_column")
    graph.add_edge("extract_keywords", "recall_metric")
    graph.add_edge("extract_keywords", "recall_value")

    graph.add_edge("recall_column", "merge_retrieved_info")
    graph.add_edge("recall_metric", "merge_retrieved_info")
    graph.add_edge("recall_value", "merge_retrieved_info")

    graph.add_edge("merge_retrieved_info", "filter_table")
    graph.add_edge("merge_retrieved_info", "filter_metric")

    graph.add_edge("filter_table", "add_extra_context")
    graph.add_edge("filter_metric", "add_extra_context")

    graph.add_edge("add_extra_context", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")

    graph.add_conditional_edges(
        "validate_sql",
        _route_after_validate,
        {"execute_sql": "execute_sql", "correct_sql": "correct_sql"},
    )
    graph.add_edge("correct_sql", "validate_sql")
    graph.add_edge("execute_sql", END)

    return graph.compile()
