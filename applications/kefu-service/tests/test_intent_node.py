# -*- coding: utf-8 -*-
"""TD-1 回归：kefu intent_node 复用统一意图架构（agent_core.intent）。

无真实 LLM/嵌入调用：monkeypatch 内核 ``classify_l1``（同步）+ ``l2_judge``（async）。
覆盖路径：
- 闲聊经 is_chitchat 短路 -> chitchat（is_chitchat 内部走真实 classify_l1 关键字链）
- CUSTOMER_SERVICE 下按业务关键词细分 订单/物流/售后
- CUSTOMER_SERVICE 但无细分词 -> knowledge
- 其他统一标签（RAG_KNOWLEDGE 等）-> knowledge
- L1 低置信回退 L2 分支中 L2 协程被真实 await（防假绿，捕获 to_thread 误包 async 回归）
- 分类器抛异常 -> 安全降级 knowledge，不向上抛

防假绿设计：``_l2`` fake 记录是否被事件循环真实 await；若 Critical #1 的
``asyncio.to_thread(classify_intent)`` 误包 async 回归，L2 协程永不被 await，
``state["awaited"]`` 为 False，相关断言失败。
"""

import asyncio

from agent_core.intent import IntentLabel, IntentResult
from agent_core.intent.models import IntentCandidate
from kefu_agent import graph as G


def _l1(label: IntentLabel, confidence: float, *, need_clarify: bool = False):
    """构造一个同步 L1 fake（仅分类段使用；is_chitchat 内部走真实 classify_l1）。"""
    return lambda _msg: IntentResult(
        primary=label, confidence=confidence,
        candidates=[IntentCandidate(label, confidence)],
        source="l1", need_clarify=need_clarify,
    )


def _l2(label: IntentLabel, confidence: float = 0.9):
    """构造一个 async L2 fake，并记录是否被真实 await（防假绿）。"""
    state = {"n": 0, "awaited": False}

    async def _f(_msg: str) -> IntentResult:
        state["n"] += 1
        state["awaited"] = True  # 若协程未被 await，此行不执行 -> 断言可捕获假绿
        return IntentResult(
            primary=label, confidence=confidence,
            candidates=[IntentCandidate(label, confidence)],
            source="l2",
        )
    _f.state = state
    return _f


def _run(msg: str, l1_fake, l2_fake):
    orig_l1, orig_l2 = G.classify_l1, G.l2_judge
    G.classify_l1, G.l2_judge = l1_fake, l2_fake
    try:
        result = asyncio.run(_invoke(msg))
        l2_state = getattr(l2_fake, "state", None)
        return result, l2_state
    finally:
        G.classify_l1, G.l2_judge = orig_l1, orig_l2


async def _invoke(msg: str) -> str:
    return (await G.intent_node({"user_message": msg}))["intent"]


def test_chitchat_short_circuits():
    # "你好" 由真实 is_chitchat（classify_l1 关键字链）判闲聊短路
    l1 = _l1(IntentLabel.RAG_KNOWLEDGE, 0.9)
    l2 = _l2(IntentLabel.RAG_KNOWLEDGE)
    intent, l2_st = _run("你好", l1, l2)
    assert intent == "chitchat"
    assert l2_st["n"] == 0    # 闲聊短路不触发 L2


def test_customer_service_routes_order():
    l1 = _l1(IntentLabel.CUSTOMER_SERVICE, 0.9)
    l2 = _l2(IntentLabel.CUSTOMER_SERVICE)
    intent, _ = _run("我的订单什么时候发货", l1, l2)
    assert intent == "order_query"


def test_customer_service_routes_logistics():
    l1 = _l1(IntentLabel.CUSTOMER_SERVICE, 0.9)
    l2 = _l2(IntentLabel.CUSTOMER_SERVICE)
    intent, _ = _run("快递到哪了", l1, l2)
    assert intent == "logistics_query"


def test_customer_service_routes_postsale():
    l1 = _l1(IntentLabel.CUSTOMER_SERVICE, 0.9)
    l2 = _l2(IntentLabel.CUSTOMER_SERVICE)
    intent, _ = _run("我要退款", l1, l2)
    assert intent == "postsale_query"


def test_customer_service_without_subkeyword_falls_to_knowledge():
    # 无业务细分词 -> CUSTOMER_SERVICE 仍归 knowledge
    l1 = _l1(IntentLabel.CUSTOMER_SERVICE, 0.9)
    l2 = _l2(IntentLabel.CUSTOMER_SERVICE)
    intent, _ = _run("我要找人工客服", l1, l2)
    assert intent == "knowledge"


def test_l1_high_confidence_used_directly():
    # L1 高置信直出分支：L2 不应被调用（防假绿：验证 L1 路径生效且 L2 未触发）
    l1 = _l1(IntentLabel.RAG_KNOWLEDGE, 0.95)
    l2 = _l2(IntentLabel.CUSTOMER_SERVICE)  # 若误走 L2 会得不同标签
    intent, l2_st = _run("你们的政策是什么", l1, l2)
    assert intent == "knowledge"
    assert l2_st["n"] == 0          # L1 高置信 -> 不进 L2
    assert l2_st["awaited"] is False


def test_l2_invoked_on_low_confidence_and_awaited():
    # L1 低置信 -> 回退 L2，且 L2 协程必须被真实 await（捕获 to_thread 误包 async 回归）
    l1 = _l1(IntentLabel.DIRECT, 0.3, need_clarify=True)
    l2 = _l2(IntentLabel.WEB_SEARCH)
    intent, l2_st = _run("今天天气怎么样", l1, l2)
    assert l2_st["n"] == 1          # L2 被调用
    assert l2_st["awaited"] is True # L2 协程被真实 await（Critical #1 修复验证）
    assert intent == "knowledge"    # WEB_SEARCH 走知识库兜底


def test_classify_failure_degrades_safely():
    # 分类器崩溃：业务关键词优先仍可达；无业务词则安全降级 knowledge 不崩。
    def _boom_l1(_msg: str) -> IntentResult:
        raise RuntimeError("embedder unavailable")
    async def _boom_l2(_msg: str) -> IntentResult:
        raise RuntimeError("LLM unavailable")

    # 含「订单」-> 即便分类器全挂也走 order_query（可达性底线，严重 #1）
    intent_order, _ = _run("我的订单呢", _boom_l1, _boom_l2)
    assert intent_order == "order_query"

    # 无业务词、分类器挂 -> 安全降级 knowledge
    intent_kb, _ = _run("随便聊聊", _boom_l1, _boom_l2)
    assert intent_kb == "knowledge"
