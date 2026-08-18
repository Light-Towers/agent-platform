"""主对话图：意图路由 → 命令分发 → Flow/知识/闲聊 → 响应。

legacy Policy → LLM 驱动的意图路由（复用 Phase 3）
legacy NLG → deepagents 输出
"""

from __future__ import annotations

from agent_core.intent import IntentLabel, classify_intent, is_chitchat
from agent_core.logging import get_logger
from langgraph.graph import END, StateGraph

from kefu_agent.commands import INTENT_TO_COMMAND, Command
from kefu_agent.flows.logistics_flow import build_logistics_flow
from kefu_agent.flows.order_flow import build_order_flow
from kefu_agent.flows.postsale_flow import build_postsale_flow
from kefu_agent.graph_rag import graph_rag_query
from kefu_agent.state import KefuState

logger = get_logger(__name__)

_order_flow = build_order_flow()
_logistics_flow = build_logistics_flow()
_postsale_flow = build_postsale_flow()

# CUSTOMER_SERVICE 大类下仍需细分的业务二级路由关键词（统一意图标签不区分订单/物流/售后，
# 这部分属于 kefu 业务流程分流，非意图识别硬编码，保留为必要业务路由）。
_ORDER_KEYWORDS = ["订单", "下单", "购买"]
_LOGISTICS_KEYWORDS = ["物流", "快递", "发货"]
_POSTSALE_KEYWORDS = ["售后", "退换", "退款", "换货", "退货", "维修"]


async def intent_node(state: KefuState) -> KefuState:
    """意图识别节点（复用统一意图架构 agent_core.intent，TD-1 修复）。

    闲聊经 ``is_chitchat`` 短路；其余走 ``classify_intent`` 取统一标签：
    - CUSTOMER_SERVICE -> 仍按业务关键词细分订单/物流/售后 Flow；
    - 其他（RAG_KNOWLEDGE / TEXT_TO_SQL / WEB_SEARCH / DIRECT / CHITCHAT 兜底）
      -> 走知识库 ``knowledge``。
    """
    message = state.get("user_message", "")

    if is_chitchat(message):
        intent = "chitchat"
    else:
        try:
            label = (await classify_intent(message)).primary
        except Exception as exc:
            # 统一意图架构（L2 LLM）不可用时，安全降级到知识库兜底，
            # 不阻断客服链路（TD-1 修复后仍需保证 LLM 缺失时的可用性）。
            logger.warning("[intent] classify_intent 失败，降级 knowledge: %s", exc)
            label = IntentLabel.DIRECT
        if label == IntentLabel.CUSTOMER_SERVICE:
            if any(kw in message for kw in _ORDER_KEYWORDS):
                intent = "order_query"
            elif any(kw in message for kw in _LOGISTICS_KEYWORDS):
                intent = "logistics_query"
            elif any(kw in message for kw in _POSTSALE_KEYWORDS):
                intent = "postsale_query"
            else:
                # 客服大类但无明确业务分流词，归入知识库应答。
                intent = "knowledge"
        else:
            # RAG_KNOWLEDGE / TEXT_TO_SQL / WEB_SEARCH / DIRECT 均走知识库。
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
