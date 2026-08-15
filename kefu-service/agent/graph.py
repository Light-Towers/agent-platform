"""主对话图：意图路由 → 命令分发 → Flow/知识/闲聊 → 响应。

atguigu_ai Policy → LLM 驱动的意图路由（复用 Phase 3）
atguigu_ai NLG → deepagents 输出
"""

from __future__ import annotations

from agent_core.logging import get_logger
from langgraph.graph import END, StateGraph

from agent.commands import INTENT_TO_COMMAND, Command
from agent.flows.logistics_flow import build_logistics_flow
from agent.flows.order_flow import build_order_flow
from agent.flows.postsale_flow import build_postsale_flow
from agent.graph_rag import graph_rag_query
from agent.state import KefuState

logger = get_logger(__name__)

_order_flow = build_order_flow()
_logistics_flow = build_logistics_flow()
_postsale_flow = build_postsale_flow()


async def intent_node(state: KefuState) -> KefuState:
    """意图识别节点（复用 Phase 3 意图识别）。"""
    message = state.get("user_message", "")

    if any(kw in message for kw in ["政策", "流程", "规定", "制度", "手册", "怎么申请", "如何申请"]):
        intent = "knowledge"
    elif any(kw in message for kw in ["订单", "下单", "购买"]):
        intent = "order_query"
    elif any(kw in message for kw in ["物流", "快递", "发货"]):
        intent = "logistics_query"
    elif any(kw in message for kw in ["售后", "退换", "退款", "换货", "退货", "维修"]):
        intent = "postsale_query"
    elif any(kw in message for kw in ["你好", "谢谢", "再见"]):
        intent = "chitchat"
    else:
        intent = "knowledge"

    return {**state, "intent": intent}


def route_by_intent(state: KefuState) -> str:
    """根据意图路由到对应节点。"""
    intent = state.get("intent", "knowledge")
    command = INTENT_TO_COMMAND.get(intent, Command.KNOWLEDGE_ANSWER)

    if command == Command.START_FLOW:
        if intent == "order_query":
            return "order_flow"
        if intent == "logistics_query":
            return "logistics_flow"
        if intent == "postsale_query":
            return "postsale_flow"
    if command == Command.CHITCHAT:
        return "chitchat"
    return "knowledge"


async def order_flow_node(state: KefuState) -> KefuState:
    """订单 Flow 子图。"""
    result = await _order_flow.ainvoke(state)
    return {**state, "response": result.get("response")}


async def logistics_flow_node(state: KefuState) -> KefuState:
    """物流 Flow 子图。"""
    result = await _logistics_flow.ainvoke(state)
    return {**state, "response": result.get("response")}


async def postsale_flow_node(state: KefuState) -> KefuState:
    """售后 Flow 子图。"""
    result = await _postsale_flow.ainvoke(state)
    return {**state, "response": result.get("response")}


async def knowledge_node(state: KefuState) -> KefuState:
    """知识库回答（GraphRAG）。"""
    query = state.get("user_message", "")
    response = await graph_rag_query(query)
    return {**state, "response": response}


async def chitchat_node(state: KefuState) -> KefuState:
    """闲聊节点。"""
    message = state.get("user_message", "")
    if "你好" in message:
        return {**state, "response": "您好，有什么可以帮您？"}
    if "谢谢" in message:
        return {**state, "response": "不客气，很高兴能帮到您！"}
    return {**state, "response": "好的，请问还有什么可以帮您？"}


def build_kefu_graph(checkpointer=None):
    """构建 kefu 主对话图。"""
    graph = StateGraph(KefuState)

    graph.add_node("intent", intent_node)
    graph.add_node("order_flow", order_flow_node)
    graph.add_node("logistics_flow", logistics_flow_node)
    graph.add_node("postsale_flow", postsale_flow_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("chitchat", chitchat_node)

    graph.set_entry_point("intent")
    graph.add_conditional_edges(
        "intent",
        route_by_intent,
        {
            "order_flow": "order_flow",
            "logistics_flow": "logistics_flow",
            "postsale_flow": "postsale_flow",
            "knowledge": "knowledge",
            "chitchat": "chitchat",
        },
    )

    for node in ["order_flow", "logistics_flow", "postsale_flow", "knowledge", "chitchat"]:
        graph.add_edge(node, END)

    return graph.compile(checkpointer=checkpointer)
