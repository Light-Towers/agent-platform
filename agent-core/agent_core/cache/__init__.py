# -*- coding: utf-8 -*-
"""语义缓存共享工具。"""

from agent_core.cache.base import BaseSemanticCache, build_cache_key
from agent_core.cache.stats import CacheStats

__all__ = ["CacheStats", "BaseSemanticCache", "build_cache_key"]
