# -*- coding: utf-8 -*-
"""统一意图识别公共 API（双轨收敛入口）。

调用方（deepagents / app）只需：
    from agent_core.intent import classify_intent, is_chitchat, IntentLabel

- ``classify_intent``：L1 嵌入粗分；高置信直接返回，低置信/需澄清自动走 L2（async）。
- ``is_chitchat``：轻量闲聊判定（L1 关键词短链），用于路由 short-circuit。
"""

from __future__ import annotations


from agent_core.intent.classifier import classify_l1, classify_l1_async
from agent_core.intent.llm_judge import l2_judge
from agent_core.intent.models import (
    L1_THRESHOLD,
    IntentLabel,
    IntentResult,
)


def is_chitchat(query: str) -> bool:
    """轻量闲聊判定：仅依赖 L1 关键词/嵌入短链，不触发 LLM。"""
    res = classify_l1(query)
    return res.primary == IntentLabel.CHITCHAT and res.confidence >= 0.7


async def classify_intent(query: str, *, model=None) -> IntentResult:
    """统一意图识别。

    Args:
        query: 用户输入。
        model: 可选 LLM 客户端/注册键；None 时使用内核默认注册客户端（L2 触发时）。

    Returns:
        IntentResult：L1 高置信直接出，否则 L2 细判；L2 失败降级 L1。
    """
    l1 = await classify_l1_async(query)
    if l1.confidence >= L1_THRESHOLD and not l1.need_clarify:
        return l1
    return await l2_judge(query, model=model)
