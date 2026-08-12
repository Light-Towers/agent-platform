"""输入 guardrail：PII 脱敏 + prompt injection 检测。

架构图标注 guardrail → cache 顺序：先脱敏再查缓存，缓存 key 用脱敏后 query。
"""

from __future__ import annotations

import os
import re
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("phone", re.compile(r"1[3-9]\d{9}")),
    ("email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    ("id_card", re.compile(r"\b\d{15}(\d{2}[\dXx])?\b")),
    ("bank_card", re.compile(r"\b\d{16,19}\b")),
    ("ip_address", re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
]

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|previous)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\/?system>", re.IGNORECASE),
    re.compile(r"<\/?prompt>", re.IGNORECASE),
    re.compile(r"reveal\s+(your|the)\s+(system\s+)?prompt", re.IGNORECASE),
]

_PII_REPLACEMENTS = {
    "phone": "[PHONE]",
    "email": "[EMAIL]",
    "id_card": "[ID_CARD]",
    "bank_card": "[BANK_CARD]",
    "ip_address": "[IP]",
}


def detect_pii(text: str) -> list[dict[str, Any]]:
    """检测文本中的 PII（不脱敏，只报告）。"""
    findings = []
    for pii_type, pattern in _PII_PATTERNS:
        for match in pattern.finditer(text):
            findings.append({
                "type": pii_type,
                "start": match.start(),
                "end": match.end(),
                "value": match.group(),
            })
    return findings


def redact_pii(text: str) -> tuple[str, list[str]]:
    """PII 脱敏：替换敏感信息为占位符。

    Returns:
        (redacted_text, redacted_types)
    """
    redacted = text
    redacted_types = []
    for pii_type, pattern in _PII_PATTERNS:
        if pattern.search(redacted):
            redacted = pattern.sub(_PII_REPLACEMENTS[pii_type], redacted)
            redacted_types.append(pii_type)
    if redacted_types:
        logger.info("PII 脱敏: %s", redacted_types)
    return redacted, redacted_types


def detect_injection(text: str) -> tuple[bool, str | None]:
    """Prompt injection 检测。

    Returns:
        (is_injection, matched_pattern)
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True, pattern.pattern
    return False, None


def guard_input(text: str) -> dict[str, Any]:
    """输入 guardrail 统一入口。

    顺序：PII 检测 → PII 脱敏 → injection 检测

    Returns:
        {
            "safe": bool,
            "redacted_text": str,
            "pii_types": list,
            "injection_detected": bool,
            "injection_pattern": str | None,
            "blocked": bool,
        }
    """
    redacted, pii_types = redact_pii(text)
    is_injection, injection_pattern = detect_injection(redacted)

    blocked = False
    if is_injection:
        logger.warning("Prompt injection 检测到: %s", injection_pattern)
        blocked = os.getenv("GUARD_BLOCK_INJECTION", "true").lower() == "true"

    return {
        "safe": not blocked,
        "redacted_text": redacted,
        "pii_types": pii_types,
        "injection_detected": is_injection,
        "injection_pattern": injection_pattern,
        "blocked": blocked,
    }
