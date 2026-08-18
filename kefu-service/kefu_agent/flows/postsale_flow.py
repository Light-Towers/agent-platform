"""售后 Flow：对应 legacy flow_postsale.yml。

LangGraph 子图：识别售后类型 → 查询售后政策 → 格式化回复。
接入真实业务服务（agent.services.query_postsale_policy）。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from kefu_agent.services import extract_issue_type, query_postsale_policy
from kefu_agent.state import KefuState


async def collect_issue_type(state: KefuState) -> KefuState:
    """从用户消息中识别售后类型到 slots。"""
    message = state.get("user_message", "")
    issue_type = await extract_issue_type(message)
    slots = dict(state.get("slots", {}))
    if issue_type:
        slots["issue_type"] = issue_type
    return {**state, "slots": slots}


async def query_postsale_policy_info(state: KefuState) -> KefuState:
    """查询售后政策。"""
    issue_type = state.get("slots", {}).get("issue_type", "未知")
    result = await query_postsale_policy(issue_type)
    return {**state, "response": result["message"] or result["policy"]}


async def format_postsale_response(state: KefuState) -> KefuState:
    """格式化售后回复（已在 query_postsale_policy_info 中完成）。"""
    return state


def build_postsale_flow():
    """构建售后 Flow 子图。"""
    graph = StateGraph(KefuState)
    graph.add_node("collect_issue_type", collect_issue_type)
    graph.add_node("query_policy", query_postsale_policy_info)
    graph.add_node("format_response", format_postsale_response)

    graph.set_entry_point("collect_issue_type")
    graph.add_edge("collect_issue_type", "query_policy")
    graph.add_edge("query_policy", "format_response")
    graph.add_edge("format_response", END)

    return graph.compile()
