"""缓存配置：阈值 / TTL / 开关，全部环境变量可调。

缓存 key = hash(intent + rewritten_query + kb_versions + tenant_id + gray_pct)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() == "true"


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


@dataclass(frozen=True)
class CacheConfig:
    cache_enabled: bool = field(default_factory=lambda: _env_bool("CACHE_ENABLED", False))
    valkey_url: str = field(default_factory=lambda: os.getenv("VALKEY_URL", "redis://localhost:6379"))

    l1_ttl_seconds: int = field(default_factory=lambda: _env_int("CACHE_L1_TTL", 3600))
    l2_ttl_seconds: int = field(default_factory=lambda: _env_int("CACHE_L2_TTL", 1800))
    l3_ttl_seconds: int = field(default_factory=lambda: _env_int("CACHE_L3_TTL", 600))

    l2_similarity_threshold: float = field(default_factory=lambda: _env_float("CACHE_L2_THRESHOLD", 0.92))
    l2_vector_dim: int = field(default_factory=lambda: _env_int("CACHE_L2_VEC_DIM", 512))

    null_cache_ttl_seconds: int = field(default_factory=lambda: _env_int("CACHE_NULL_TTL", 60))
    null_cache_enabled: bool = field(default_factory=lambda: _env_bool("CACHE_NULL_ENABLED", True))

    kb_versions: dict[str, str] = field(default_factory=lambda: {
        "wenda": os.getenv("KB_VERSION_WENDA", "v1"),
        "zhiku": os.getenv("KB_VERSION_ZHIKU", "v1"),
        "kefu": os.getenv("KB_VERSION_KEFU", "v1"),
    })
    gray_pct: float = field(default_factory=lambda: _env_float("GRAY_PCT", 0.0))
    tenant_id: str = field(default_factory=lambda: os.getenv("TENANT_ID", "default"))

    index_name: str = "semantic_cache_idx"
    l1_prefix: str = "cache:l1:"
    l2_prefix: str = "cache:l2:"
    l3_prefix: str = "cache:l3:"
    null_prefix: str = "cache:null:"


_config: CacheConfig | None = None


def get_cache_config() -> CacheConfig:
    global _config
    if _config is None:
        _config = CacheConfig()
    return _config


def refresh_config() -> CacheConfig:
    global _config
    _config = CacheConfig()
    return _config
