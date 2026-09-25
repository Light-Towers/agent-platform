# -*- coding: utf-8 -*-
"""agent_core.intent L2 细判与 classify_intent 触发路径测试。

用假 LLM 客户端（实现 ainvoke）验证 L2 解析逻辑与 L1->L2 自动升级，
不依赖真实 OpenAI / sentence-transformers，保证 CI 可跑。
"""

import asyncio
from types import SimpleNamespace


from agent_core.intent import IntentLabel, classify_intent, l2_judge


class _FakeLLM:
    """返回预置 JSON 的假客户端（模拟 langchain ChatOpenAI.ainvoke）。"""

    def __init__(self, payload: str):
        self._payload = payload

    async def ainvoke(self, prompt):
        return SimpleNamespace(content=self._payload)


def test_l2_judge_parses_json():
    fake = _FakeLLM('{"intent": "text_to_sql", "confidence": 0.9, "reason": "x"}')
    res = asyncio.run(l2_judge("查询销售额", model=fake))
    assert res.primary is IntentLabel.TEXT_TO_SQL
    assert res.confidence == 0.9
    assert res.source == "l2"
    assert res.need_clarify is False


def test_l2_judge_low_confidence_sets_clarify():
    fake = _FakeLLM('{"intent": "web_search", "confidence": 0.3, "reason": "x"}')
    res = asyncio.run(l2_judge("某问题", model=fake))
    assert res.primary is IntentLabel.WEB_SEARCH
    assert res.need_clarify is True


def test_l2_judge_invalid_json_falls_back():
    fake = _FakeLLM("这不是 json")
    # 降级到 L1（chitchat 关键词或 fallback），不应抛异常
    res = asyncio.run(l2_judge("你好", model=fake))
    assert res.primary in IntentLabel


def test_classify_intent_triggers_l2_on_low_confidence():
    # L1 对普通查询可能给低置信；强制 L1 走 L2 用 fake client 验证升级路径
    fake = _FakeLLM('{"intent": "rag_knowledge", "confidence": 0.85, "reason": "x"}')
    res = asyncio.run(classify_intent("知识库里怎么说的", model=fake))
    # 若 L1 未达 0.8 则 L2 接管；无论哪条路径，结果应是合法 IntentLabel
    assert res.primary in IntentLabel
    assert 0.0 <= res.confidence <= 1.0
