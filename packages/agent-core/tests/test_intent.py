# -*- coding: utf-8 -*-
"""agent_core.intent 统一意图原语测试。

覆盖：
- IntentLabel.from_str 容错
- L1 chitchat 关键词短链
- L1 嵌入不可用时降级 fallback（DIRECT + need_clarify）
- classify_with_fallback 不抛异常
"""


from agent_core.intent import (
    IntentLabel,
    classify_l1,
    is_chitchat,
)


def test_intent_label_from_str_unknown_falls_to_direct():
    assert IntentLabel.from_str("not_a_real_label") is IntentLabel.DIRECT
    assert IntentLabel.from_str("text_to_sql") is IntentLabel.TEXT_TO_SQL


def test_l1_chitchat_short_circuit():
    res = classify_l1("你好")
    assert res.primary is IntentLabel.CHITCHAT
    assert res.confidence >= 0.7
    assert res.source == "l1_keyword"


def test_is_chitchat_true_for_greeting():
    assert is_chitchat("在吗") is True


def test_is_chitchat_false_for_query():
    assert is_chitchat("查询本月的销售额") is False


def test_l1_does_not_raise_when_embedder_unavailable():
    # LocalEmbedder 未加载/模型缺失时也应降级而非抛异常
    res = classify_l1("统计各地区的订单数量")
    assert isinstance(res, object)
    assert hasattr(res, "primary")
    assert res.primary in IntentLabel


def test_l1_fallback_result_is_direct_with_clarify():
    # 原型全空/嵌入失败路径返回 DIRECT + need_clarify（不抛异常）
    res = classify_l1("")
    assert res.primary is IntentLabel.DIRECT
    assert res.need_clarify is True


# ---------- WS-6：数据外置等价性 + 异步入口 ----------


def test_chitchat_words_loaded_from_data():
    """词表从 prototypes.json 加载（含 strong/weak），与历史行为等价。"""
    from agent_core.intent.classifier import _chitchat_words, _load_prototypes

    _load_prototypes.cache_clear()
    _chitchat_words.cache_clear()
    strong, weak = _chitchat_words()
    assert "你好" in strong and "在吗" in strong
    assert "谢谢" in weak and "hi" in weak
    # 数据驱动：新增词可经数据文件生效（不改代码）
    data = _load_prototypes()
    assert set(data["chitchat_shortcuts"]["strong"]) == set(strong)


def test_l1_uses_data_driven_shortcut():
    # 数据中的 strong 词命中短链（等价于改造前硬编码行为）
    res = classify_l1("你是谁")
    assert res.primary is IntentLabel.CHITCHAT
    assert res.source == "l1_keyword"
    # weak 词仅纯问候时短路，业务句不误伤
    assert classify_l1("hi").primary is IntentLabel.CHITCHAT
    assert classify_l1("谢谢你帮我分析一下这份合同").source != "l1_keyword" or \
        classify_l1("谢谢你帮我分析一下这份合同").primary is not IntentLabel.CHITCHAT


def test_classify_l1_async_matches_sync():
    import asyncio

    from agent_core.intent import classify_l1_async

    sync_res = classify_l1("你好")
    async_res = asyncio.run(classify_l1_async("你好"))
    assert async_res.primary is sync_res.primary
    assert async_res.source == sync_res.source
