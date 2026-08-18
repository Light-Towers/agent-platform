# -*- coding: utf-8 -*-
"""app 与内核统一意图的桥接层（TB-9 双轨收敛）。

deepagents 与 app 曾各有一套意图标签，内核 ``agent_core.intent.IntentLabel``
是收敛后的单一真源。本模块负责：
1. 把内核 ``IntentLabel`` 映射到 app 的 ``route`` capability（sql/rag/search/direct/mcp）。
2. 封装 L1 轻量 short-circuit（chitchat -> direct），供 graph.route_node 在 LLM 路由前拦截。

设计原则：L1 仅作 chitchat short-circuit，不替换 app 既有的 LLM 主路由
（``decide_route`` 是 eval 门禁基线，必须保持），确保评测 golden 不受影响。
"""

from __future__ import annotations

from agent_core.intent import IntentLabel, is_chitchat

# 内核统一意图 -> app route capability 的映射（单一真源）。
# - text_to_sql        -> sql
# - rag_knowledge      -> rag
# - web_search         -> search
# - customer_service   -> direct（app 无独立客服子链路，归并直答）
# - chitchat           -> direct
# - direct             -> direct
_INTENT_TO_CAPABILITY = {
    IntentLabel.TEXT_TO_SQL: "sql",
    IntentLabel.RAG_KNOWLEDGE: "rag",
    IntentLabel.WEB_SEARCH: "search",
    IntentLabel.CUSTOMER_SERVICE: "direct",
    IntentLabel.CHITCHAT: "direct",
    IntentLabel.DIRECT: "direct",
}


def map_intent_to_capability(label: IntentLabel) -> str:
    """内核统一意图 -> app route capability。

    注意：当前 ``graph.route_node`` 仅用 ``l1_route_hint`` 做 chitchat 短路，
    未启用 L1 粗分直接路由（保留 ``decide_route`` LLM 主判以稳定 eval 基线）。
    本函数是双轨标签映射的单一真源，预留给未来可选启用 L1 粗分路由时使用。
    """
    return _INTENT_TO_CAPABILITY.get(label, "direct")


def l1_route_hint(question: str) -> str | None:
    """L1 轻量 short-circuit。

    仅对高置信 chitchat 直接返回 ``direct``；其余返回 None，
    交由 ``decide_route`` 做 LLM 主路由。不触发 LLM 调用。
    """
    if is_chitchat(question):
        return "direct"
    return None
