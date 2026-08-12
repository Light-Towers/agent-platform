"""输出 guard：敏感信息泄漏检测 + 答案质量基础检查。

复用 kefu guard 节点模式。
"""

from __future__ import annotations

import re
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_OUTPUT_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("phone", re.compile(r"1[3-9]\d{9}")),
    ("id_card", re.compile(r"\b\d{15}(\d{2}[\dXx])?\b")),
    ("bank_card", re.compile(r"\b\d{16,19}\b")),
]

_HALLUCINATION_MARKERS = [
    "我不知道",
    "无法回答",
    "作为AI",
    "作为语言模型",
]


def detect_output_pii(text: str) -> list[str]:
    """检测输出中是否泄漏 PII。"""
    leaked = []
    for pii_type, pattern in _OUTPUT_PII_PATTERNS:
        if pattern.search(text):
            leaked.append(pii_type)
    return leaked


def check_quality(text: str) -> dict[str, Any]:
    """基础质量检查。"""
    if not text or len(text.strip()) < 2:
        return {"pass": False, "reason": "输出过短"}

    for marker in _HALLUCINATION_MARKERS:
        if marker in text:
            return {"pass": True, "warning": f"含回避标记: {marker}"}

    return {"pass": True}


def guard_output(text: str) -> dict[str, Any]:
    """输出 guardrail 统一入口。

    Returns:
        {
            "safe": bool,
            "text": str,
            "pii_leaked": list,
            "quality": dict,
        }
    """
    pii_leaked = detect_output_pii(text)
    quality = check_quality(text)

    if pii_leaked:
        logger.warning("输出 PII 泄漏: %s", pii_leaked)

    return {
        "safe": len(pii_leaked) == 0 and quality["pass"],
        "text": text,
        "pii_leaked": pii_leaked,
        "quality": quality,
    }
