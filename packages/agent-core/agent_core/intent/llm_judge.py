# -*- coding: utf-8 -*-
"""L2 LLM 细判（意图澄清 + 低置信兜底）。

从 deepagents ``agent/intent/llm_judge.py`` 下沉到内核。遵循框架无关护栏：
不直接 import openai / langchain；通过 ``agent_core.llm.get_llm_client()``
获取已注册的统一 LLM 客户端（默认 ChatOpenAI），调用其 ``.ainvoke``。

低于 L1_THRESHOLD 或 L1 need_clarify 时调用 L2 重新判定；
L2 置信度 < CLARIFY_THRESHOLD 时置 need_clarify，交由调用方反问。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_core.intent.models import (
    CLARIFY_THRESHOLD,
    IntentCandidate,
    IntentLabel,
    IntentResult,
)
from agent_core.intent.classifier import classify_l1_async, _keyword_rule

logger = logging.getLogger(__name__)

_PROMPT = """你是意图分类器。用户问题：{query}

候选意图（只选其一）：
- text_to_sql：用户想用自然语言查询结构化数据库（表/字段/SQL 类问题）
- rag_knowledge：用户想从私有知识库/文档检索答案
- web_search：用户需要实时网页/联网信息
- customer_service：客服类咨询（订单/退款/售后等）
- chitchat：闲聊/问候/无意义对话
- direct：通用直答，不属于以上任何一类

要求：严格输出 JSON，格式 {{"intent": "...", "confidence": 0.0-1.0, "reason": "..."}}。
"""


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    """从 LLM 输出解析 JSON（容忍代码块包裹）。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        return None


def _resolve_client(model):
    """解析 LLM 客户端：接受已构建客户端、注册键名或 None（默认注册表）。"""
    if model is None:
        from agent_core.llm import get_llm_client

        return get_llm_client()
    if isinstance(model, str):
        from agent_core.llm import get_llm_client

        return get_llm_client(model)
    return model  # 已是客户端实例（应实现 ainvoke）


async def l2_judge(query: str, *, model=None) -> IntentResult:
    """L2 LLM 细判。失败时降级到 L1+关键词。"""
    client = _resolve_client(model)
    try:
        resp = await client.ainvoke(_PROMPT.format(query=query))
        content = getattr(resp, "content", None)
        if isinstance(content, list):
            # langchain 多模态 content 取文本块
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
        parsed = _parse_llm_json(content or "")
        if parsed:
            label = IntentLabel.from_str(str(parsed.get("intent", "")))
            conf = float(parsed.get("confidence", 0.5))
            return IntentResult(
                primary=label, confidence=conf,
                candidates=[IntentCandidate(label, conf)],
                source="l2",
                need_clarify=conf < CLARIFY_THRESHOLD,
            )
    except Exception as e:
        logger.warning("L2 intent judge failed, fallback to L1: %s", e)

    # 降级：L1 嵌入 + 关键词（经异步入口，不阻塞事件循环，WS-6）
    l1 = await classify_l1_async(query)
    if l1.primary != IntentLabel.DIRECT or l1.source != "l1_fallback":
        return l1
    kw = _keyword_rule(query)
    return kw or l1
