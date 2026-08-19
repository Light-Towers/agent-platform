"""灰度发布：按 user_id % 100 < gray_pct 分流。

新 prompt / 新链路灰度切换，对比 SLO。
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


def _get_gray_pct() -> float:
    """从环境变量获取灰度比例（0-100）。"""
    return float(os.getenv("GRAY_PCT", "0"))


def is_in_gray(user_id: str, gray_pct: float | None = None) -> bool:
    """判断用户是否在灰度范围内。

    Args:
        user_id: 用户标识
        gray_pct: 灰度比例（0-100），None 时从环境变量读取

    Returns:
        True 表示走新链路，False 表示走旧链路
    """
    if gray_pct is None:
        gray_pct = _get_gray_pct()

    if gray_pct <= 0:
        return False
    if gray_pct >= 100:
        return True

    hash_val = int(hashlib.md5(user_id.encode("utf-8")).hexdigest(), 16) % 100
    return hash_val < gray_pct


def get_gray_config() -> dict[str, Any]:
    """返回当前灰度配置。"""
    return {
        "gray_pct": _get_gray_pct(),
        "enabled": _get_gray_pct() > 0,
    }
