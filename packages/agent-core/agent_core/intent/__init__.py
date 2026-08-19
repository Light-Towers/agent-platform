# -*- coding: utf-8 -*-
"""统一意图识别原语（双轨收敛 TB-9）。

下沉自 deepagents ``agent/intent``，作为 app 与 deepagents 共用的内核能力。
遵循框架无关护栏：不依赖 langchain/openai 顶层 import，LLM 经 ``agent_core.llm`` 注册表。
"""

from agent_core.intent.api import classify_intent, is_chitchat
from agent_core.intent.classifier import classify_l1
from agent_core.intent.llm_judge import l2_judge
from agent_core.intent.models import (
    IntentLabel,
    IntentResult,
    IntentCandidate,
    L1_THRESHOLD,
    CLARIFY_THRESHOLD,
)

__all__ = [
    "IntentLabel",
    "IntentResult",
    "IntentCandidate",
    "L1_THRESHOLD",
    "CLARIFY_THRESHOLD",
    "classify_intent",
    "is_chitchat",
    "classify_l1",
    "l2_judge",
]
