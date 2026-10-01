# -*- coding: utf-8 -*-
"""args/文本摘要（单一实现）：observe_tool 与 Skill 中间件共用，禁止各自实现。

全量 args/result 全文不入事件（在 Trajectory / Langfuse），事件只带摘要。
"""

from __future__ import annotations

from typing import Any

__all__ = ["truncate", "summarize_args"]

_TRUNCATE_LIMIT = 512


def truncate(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    """超长文本截断（追加可见标记，防静默截断误判为完整内容）。"""
    return text if len(text) <= limit else text[:limit] + "…<truncated>"


def summarize_args(args: dict[str, Any] | None) -> dict[str, str]:
    """入参摘要：逐值 repr 截断 512 字符（并发安全：只读入参）。"""
    return {k: truncate(repr(v)) for k, v in (args or {}).items()}
