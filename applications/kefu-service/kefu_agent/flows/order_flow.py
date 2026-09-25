"""订单 Flow：对应 legacy flow_order.yml。

LangGraph 子图：收集订单 ID → 查询订单信息 → 格式化回复。
接入真实业务服务（agent.services.query_order）。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from kefu_agent.services import extract_order_id, query_order
from kefu_agent.state import KefuState


async def collect_order_id(state: KefuState) -> KefuState:
    """从用户消息中提取订单 ID 到 slots。"""
    message = state.get("user_message", "")
    order_id = extract_order_id(message)
    slots = dict(state.get("slots", {}))
    if order_id:
        slots["order_id"] = order_id
    return {**state, "slots": slots}


async def query_order_info(state: KefuState) -> KefuState:
    """查询订单信息。"""
    order_id = state.get("slots", {}).get("order_id")
    result = await query_order(order_id)
    return {**state, "response": result["message"] or _format_order(result["order"])}


def _format_order(order: dict | None) -> str:
    if not order:
        return "未找到该订单。"
    items = "、".join(order.get("items", []))
    return (
        f"订单号 {order['order_id']}：\n"
        f"  状态：{order['status']}\n"
        f"  金额：¥{order['amount']:.2f}\n"
        f"  商品：{items}\n"
        f"  下单时间：{order['created_at']}"
    )


async def format_order_response(state: KefuState) -> KefuState:
    """格式化订单回复（已在 query_order_info 中完成）。"""
    return state


def build_order_flow():
    """构建订单 Flow 子图。"""
    graph = StateGraph(KefuState)
    graph.add_node("collect_order_id", collect_order_id)
    graph.add_node("query_order_info", query_order_info)
    graph.add_node("format_response", format_order_response)

    graph.set_entry_point("collect_order_id")
    graph.add_edge("collect_order_id", "query_order_info")
    graph.add_edge("query_order_info", "format_response")
    graph.add_edge("format_response", END)

    return graph.compile()
