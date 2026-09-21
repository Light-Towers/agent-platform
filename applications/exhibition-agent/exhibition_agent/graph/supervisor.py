"""最小 Supervisor 图构建 + 运行入口（LangGraph StateGraph）。

复用平台已有 langgraph，不引入 langchain Chain/Retriever/Agent。
LLM 可观测 callbacks 由调用方（server.py）从 LLMObsBackend 获取并传入，run_supervisor 不自动注入。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from exhibition_agent.graph.nodes import emit_trace, run_skill, select_skill
from exhibition_agent.graph.state import ExhibitionAgentState


def build_graph():
    """构建并编译 Supervisor 图：select_skill → run_skill → emit_trace → END。"""
    graph = StateGraph(ExhibitionAgentState)

    graph.add_node("select_skill", select_skill)
    graph.add_node("run_skill", run_skill)
    graph.add_node("emit_trace", emit_trace)

    graph.add_edge(START, "select_skill")
    graph.add_edge("select_skill", "run_skill")
    graph.add_edge("run_skill", "emit_trace")
    graph.add_edge("emit_trace", END)

    return graph.compile()


async def run_supervisor(
    initial_state: dict[str, Any],
    *,
    callbacks: list[Any] | None = None,
) -> dict[str, Any]:
    """运行 Supervisor 图，返回最终 state。

    initial_state 须含：query / params / execution_context / execution_context_header /
    warehouse_client / context_mode / trace_recorder。

    callbacks：LLM 可观测 callback handler 列表（由调用方从 LLMObsBackend.get_callbacks() 获取）。
    不传则不接入 LLM 可观测 trace（测试默认路径）。
    """
    if "sql_statements" not in initial_state:
        initial_state["sql_statements"] = []
    graph = build_graph()
    config: dict[str, Any] | None = {"callbacks": callbacks} if callbacks else None
    return await graph.ainvoke(initial_state, config=config)
