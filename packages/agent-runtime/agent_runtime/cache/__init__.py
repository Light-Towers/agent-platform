"""语义缓存：单一 Valkey 实现 + 显式关闭后端 + 唯一工厂。"""

from agent_runtime.cache.config import (
    CacheConfig,
    CacheConfigError,
    get_cache_config,
    redact_url,
    reset_cache_config,
)
from agent_runtime.cache.factory import close_cache, get_cache, reset_cache_for_tests

__all__ = [
    "CacheConfig",
    "CacheConfigError",
    "close_cache",
    "get_cache",
    "get_cache_config",
    "redact_url",
    "reset_cache_config",
    "reset_cache_for_tests",
]
