# -*- coding: utf-8 -*-
"""deterministic._compose 多模态合成测试（plan-image-qa-fullstack §刀3 核心判据）。

有图 + vl_llm ⇒ ainvoke 收到 content 为 list 且含 image_url/data URI；
无图 ⇒ 逐字保持纯文本 str（零回归面）。
"""

from __future__ import annotations

import asyncio

from agent_server.planners.deterministic import DeterministicPlanner


class _StubLLM:
    def __init__(self):
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return type("R", (), {"content": "ok"})()


def test_compose_multimodal_with_images():
    planner = DeterministicPlanner()
    text_llm = _StubLLM()
    vl_llm = _StubLLM()
    asyncio.run(planner._compose(
        "这张图是什么", ["证据1"], [], text_llm,
        images=["data:image/png;base64,AAAA"], vl_llm=vl_llm,
    ))
    assert len(vl_llm.calls) == 1, "有图应调用 VL client"
    assert len(text_llm.calls) == 0, "有图不应调用文本 client"
    user_msg = vl_llm.calls[0][1]
    assert isinstance(user_msg["content"], list)
    assert any(b.get("type") == "image_url" for b in user_msg["content"])
    assert any(
        "data:image/png;base64,AAAA" in str(b.get("image_url", {}))
        for b in user_msg["content"]
    )


def test_compose_text_when_no_images():
    planner = DeterministicPlanner()
    text_llm = _StubLLM()
    vl_llm = _StubLLM()
    asyncio.run(planner._compose(
        "问题", ["证据1"], [], text_llm, vl_llm=vl_llm,
    ))
    assert len(text_llm.calls) == 1
    assert len(vl_llm.calls) == 0
    user_msg = text_llm.calls[0][1]
    assert isinstance(user_msg["content"], str), "无图必须是纯文本（零回归）"


def test_compose_text_fallback_when_vl_missing():
    """有图但 vl_llm=None（未配 VL）⇒ 降级用文本 client，不崩。"""
    planner = DeterministicPlanner()
    text_llm = _StubLLM()
    asyncio.run(planner._compose(
        "问题", ["证据1"], [], text_llm,
        images=["data:image/png;base64,AAAA"], vl_llm=None,
    ))
    assert len(text_llm.calls) == 1
    assert isinstance(text_llm.calls[0][1]["content"], str)
