"""物流 Flow：对应 atguigu_ai flow_logistics.yml。

LangGraph 子图：收集物流单号 → 查询物流状态 → 格式化回复。
接入真实业务服务（agent.services.query_logistics）。
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from agent.state import KefuState
from agent.services import extract_tracking_id, query_logistics


async def collect_tracking_id(state: KefuState) -> KefuState:
    """从用户消息中提取物流单号到 slots。"""
    message = state.get("user_message", "")
    tracking_id = extract_tracking_id(message)
    slots = dict(state.get("slots", {}))
    if tracking_id:
        slots["tracking_id"] = tracking_id
    return {**state, "slots": slots}


async def query_logistics_info(state: KefuState) -> KefuState:
    """查询物流信息。"""
    tracking_id = state.get("slots", {}).get("tracking_id")
    result = await query_logistics(tracking_id)
    return {**state, "response": result["message"] or _format_logistics(result["logistics"])}


def _format_logistics(logistics: dict | None) -> str:
    if not logistics:
        return "未找到该物流信息。"
    return (
        f"物流单号 {logistics['tracking_id']}：\n"
        f"  承运商：{logistics['carrier']}\n"
        f"  状态：{logistics['status']}\n"
        f"  当前位置：{logistics['location']}\n"
        f"  预计到达：{logistics['eta']}"
    )


async def format_logistics_response(state: KefuState) -> KefuState:
    """格式化物流回复（已在 query_logistics_info 中完成）。"""
    return state


def build_logistics_flow():
    """构建物流 Flow 子图。"""
    graph = StateGraph(KefuState)
    graph.add_node("collect_tracking_id", collect_tracking_id)
    graph.add_node("query_logistics", query_logistics_info)
    graph.add_node("format_response", format_logistics_response)

    graph.set_entry_point("collect_tracking_id")
    graph.add_edge("collect_tracking_id", "query_logistics")
    graph.add_edge("query_logistics", "format_response")
    graph.add_edge("format_response", END)

    return graph.compile()
