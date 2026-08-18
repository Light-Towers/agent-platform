# -*- coding: utf-8 -*-
"""app 意图桥接测试（TB-9 双轨收敛）。

验证内核统一意图 -> app route capability 的映射，以及 L1 chitchat
short-circuit 行为；不依赖 LLM/嵌入模型，保证 CI 可跑。
"""


from agent_core.intent import IntentLabel

from app.agent.intent_bridge import l1_route_hint, map_intent_to_capability


def test_map_intent_to_capability():
    assert map_intent_to_capability(IntentLabel.TEXT_TO_SQL) == "sql"
    assert map_intent_to_capability(IntentLabel.RAG_KNOWLEDGE) == "rag"
    assert map_intent_to_capability(IntentLabel.WEB_SEARCH) == "search"
    assert map_intent_to_capability(IntentLabel.CHITCHAT) == "direct"
    assert map_intent_to_capability(IntentLabel.CUSTOMER_SERVICE) == "direct"
    assert map_intent_to_capability(IntentLabel.DIRECT) == "direct"


def test_l1_chitchat_short_circuit_returns_direct():
    assert l1_route_hint("你好呀") == "direct"


def test_l1_non_chitchat_returns_none():
    # 非闲聊不下 L1 结论，交由 decide_route 做 LLM 主路由（eval 基线不动）
    assert l1_route_hint("查询上个月的销售总额") is None
