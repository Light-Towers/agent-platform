"""主对话图：意图路由 → 命令分发 → Flow/知识/闲聊 → 响应。

legacy Policy → LLM 驱动的意图路由（复用 Phase 3）
legacy NLG → deepagents 输出
"""

from __future__ import annotations

import asyncio

from agent_core.intent import IntentLabel, IntentResult, is_chitchat
from agent_core.intent.classifier import classify_l1
from agent_core.intent.llm_judge import l2_judge
from agent_core.intent.models import L1_THRESHOLD
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


def _route_by_business_keywords(message: str) -> str | None:
    """按业务关键词细分订单/物流/售后 Flow（零依赖，永远可达）。

    业务分流词优先于闲聊/统一分类器：保证「寒暄+诉求」复合消息
    （如「你好，帮我查一下订单」）的诉求不被闲聊短路掩盖（TD-1 修复后收尾）。
    """
    if any(kw in message for kw in _ORDER_KEYWORDS):
        return "order_query"
    if any(kw in message for kw in _LOGISTICS_KEYWORDS):
        return "logistics_query"
    if any(kw in message for kw in _POSTSALE_KEYWORDS):
        return "postsale_query"
    return None


async def intent_node(state: KefuState) -> KefuState:
    """意图识别节点（复用统一意图架构 agent_core.intent，TD-1 修复）。

    路由优先级（收尾纠偏）：
    1. 业务关键词先行细分 —— 订单/物流/售后 Flow 零依赖永远可达；
    2. 无业务关键词时，闲聊经 ``is_chitchat`` 短路；
    3. 其余走 ``classify_intent`` 取统一标签（CUSTOMER_SERVICE / 其他）；
    4. 分类器不可用（无嵌入/无 LLM）时，安全回退业务关键词分流，
       仍无命中才走知识库兜底 —— 保住标准安装环境下的可达性底线（严重 #1 修复）。
    """
    message = state.get("user_message", "")

    # 1. 业务关键词优先（恢复旧优先级，解决闲聊短路掩盖诉求）
    intent = _route_by_business_keywords(message)
    if intent:
        return {**state, "intent": intent}

    # 2. 无业务诉求时再判闲聊
    if await asyncio.to_thread(is_chitchat, message):
        intent = "chitchat"
    else:
        # 3. 统一意图分类：L1 同步嵌入推理放进线程池（不阻塞事件循环，严重 #3），
        #    L2 LLM 细判为原生 async 直接 await（避免 asyncio.to_thread 误包 async 函数
        #    导致 coroutine 永不被 await、分类器实质失效的回归，Critical #1）。
        try:
            l1: IntentResult = await asyncio.to_thread(classify_l1, message)
            if l1.confidence >= L1_THRESHOLD and not l1.need_clarify:
                label = l1.primary
            else:
                label = (await l2_judge(message)).primary
        except Exception as exc:
            # 4. 分类器不可用（L1 嵌入缺失 / L2 LLM 未配置）时，安全回退知识库兜底
            #    （业务关键词已在第 1 步判定为 None，故此处直接 knowledge，不再借
            #    IntentLabel.DIRECT 表达，语义更清晰，建议 #5）。
            logger.warning("[intent] 意图分类失败，降级 knowledge: %s", exc)
            intent = "knowledge"
            return {**state, "intent": intent}
        if label == IntentLabel.CUSTOMER_SERVICE:
            # 业务关键词未命中但被判为客服大类，归入知识库应答。
            intent = "knowledge"
        else:
            # RAG_KNOWLEDGE / TEXT_TO_SQL / WEB_SEARCH / DIRECT / CHITCHAT 兜底均走知识库。
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
