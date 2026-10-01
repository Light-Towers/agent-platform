"""灰度发布：按 ``sha256(user_id) % 100 < gray_pct`` 分流。

新 prompt / 新链路灰度切换，对比 SLO。

分桶本身不需密码学强度，但 ``user_id`` 属可识别信息，故不用 MD5：
CodeQL ``py/weak-sensitive-data-hashing`` 官方建议为「非口令场景用 SHA-2」。
注意：换哈希函数会重排已有分桶人群（当前 ``GRAY_PCT`` 默认 0、分桶不持久化，无生产影响）。
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

    hash_val = int(hashlib.sha256(user_id.encode("utf-8")).hexdigest(), 16) % 100
    return hash_val < gray_pct


def get_gray_config() -> dict[str, Any]:
    """返回当前灰度配置。"""
    return {
        "gray_pct": _get_gray_pct(),
        "enabled": _get_gray_pct() > 0,
    }
