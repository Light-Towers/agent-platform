"""联邦缓存上下文：租户 / KB 版本 / 灰度。

TTL、阈值、Valkey URL、索引与队列参数统一由 ``agent_runtime.cache`` 负责
（ADR-0013 C：开发/测试与生产同一 Valkey 实现），本文件只保留联邦自己的
流水线上下文。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from agent_core.config import env_float

_KB_OVERRIDES: dict[str, str] = {}


def _env_kb_versions() -> dict[str, str]:
    values = {
        "wenda": os.getenv("KB_VERSION_WENDA", "v1"),
        "knowledge": os.getenv("KB_VERSION_KNOWLEDGE", "v1"),
        "kefu": os.getenv("KB_VERSION_KEFU", "v1"),
    }
    values.update(_KB_OVERRIDES)
    return values


@dataclass(frozen=True)
class CacheContext:
    tenant_id: str = field(default_factory=lambda: os.getenv("TENANT_ID", "default"))
    gray_pct: float = field(default_factory=lambda: env_float("GRAY_PCT", 0.0))
    kb_versions: dict[str, str] = field(default_factory=_env_kb_versions)


_context: CacheContext | None = None


def get_cache_context() -> CacheContext:
    global _context
    if _context is None:
        _context = CacheContext()
    return _context


def set_kb_version(subservice: str, version: str) -> None:
    """运行时更新某子服务 KB 版本；后续 key 立即变化（旧条目由 epoch/ TTL 清理）。"""
    global _context
    _KB_OVERRIDES[subservice] = version
    _context = CacheContext()


def reset_cache_context() -> None:
    """测试/配置热更新用。"""
    global _context
    _KB_OVERRIDES.clear()
    _context = None


__all__ = [
    "CacheContext",
    "get_cache_context",
    "reset_cache_context",
    "set_kb_version",
]
