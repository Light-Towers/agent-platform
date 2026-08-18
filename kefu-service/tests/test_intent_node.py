# -*- coding: utf-8 -*-
"""TD-1 回归：kefu intent_node 复用统一意图架构（agent_core.intent）。

无真实 LLM/嵌入调用：monkeypatch classify_intent 为可控 async fake。
覆盖路径：
- 闲聊经 is_chitchat 短路 -> chitchat
- CUSTOMER_SERVICE 下按业务关键词细分 订单/物流/售后
- CUSTOMER_SERVICE 但无细分词 -> knowledge
- 其他统一标签（RAG_KNOWLEDGE 等）-> knowledge
- classify_intent 抛异常 -> 安全降级 knowledge（不崩）
"""

import asyncio

from agent_core.intent import IntentLabel, IntentResult
from kefu_agent.graph import intent_node


def _fake_classify(label: IntentLabel):
    async def _f(_msg: str) -> IntentResult:
        return IntentResult(primary=label, confidence=0.9)
    return _f


def _run(msg: str, classify):
    import kefu_agent.graph as G

    orig = G.classify_intent
    G.classify_intent = classify
    try:
        return asyncio.run(intent_node({"user_message": msg}))["intent"]
    finally:
        G.classify_intent = orig


def test_chitchat_short_circuits():
    # "你好" 由 is_chitchat 规则判闲聊，不触发 classify_intent
    intent = _run("你好", _fake_classify(IntentLabel.RAG_KNOWLEDGE))
    assert intent == "chitchat"


def test_customer_service_routes_order():
    intent = _run("我的订单什么时候发货", _fake_classify(IntentLabel.CUSTOMER_SERVICE))
    assert intent == "order_query"


def test_customer_service_routes_logistics():
    intent = _run("快递到哪了", _fake_classify(IntentLabel.CUSTOMER_SERVICE))
    assert intent == "logistics_query"


def test_customer_service_routes_postsale():
    intent = _run("我要退款", _fake_classify(IntentLabel.CUSTOMER_SERVICE))
    assert intent == "postsale_query"


def test_customer_service_without_subkeyword_falls_to_knowledge():
    intent = _run("我要找人工客服", _fake_classify(IntentLabel.CUSTOMER_SERVICE))
    assert intent == "knowledge"


def test_non_customer_service_routes_knowledge():
    intent = _run("你们的政策是什么", _fake_classify(IntentLabel.RAG_KNOWLEDGE))
    assert intent == "knowledge"


def test_classify_intent_failure_degrades_safely():
    async def _boom(_msg: str) -> IntentResult:
        raise RuntimeError("LLM unavailable")

    # 即使 classifier 崩溃，intent_node 也必须安全降级，不向上抛
    intent = _run("我的订单呢", _boom)
    assert intent == "knowledge"
