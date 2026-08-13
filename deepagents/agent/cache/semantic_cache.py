"""语义缓存统一入口：L1 精确 → L2 语义 → 未命中 → 异步写入。

查询流程：NullCache → L1 → L2 → None
写入流程（异步）：L1 + L2 + NullCache（空值）
命中率统计：get / hit / miss 上报 Langfuse
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
from agent_core.cache import CacheStats
from agent_core.logging import get_logger

from agent.cache.config import get_cache_config
from agent.cache.layers import (
    L1Cache,
    L2Cache,
    NullCache,
    _build_cache_key,
)

logger = get_logger(__name__)

_stats = CacheStats()


def _get_embedding(text: str) -> np.ndarray | None:
    """获取 query 的 embedding 向量（用于 L2 语义缓存）。

    复用 L1 分类器的 sentence-transformers 模型，但向量空间独立。
    """
    try:
        from agent.intent.classifier import _embedder

        if _embedder is None:
            return None
        vec = _embedder.encode([text], normalize_embeddings=True)[0]
        return np.array(vec, dtype=np.float32)
    except Exception:
        return None


class SemanticCache:
    """语义缓存统一入口。"""

    @staticmethod
    async def get(
        intent: str,
        rewritten_query: str,
        query_vec: np.ndarray | None = None,
    ) -> dict[str, Any] | None:
        """查询缓存。

        Args:
            intent: 意图标签
            rewritten_query: 改写后的 query
            query_vec: query 的 embedding 向量（可选，用于 L2）

        Returns:
            缓存值（含 _layer 字段）或 None（未命中）
        """
        cfg = get_cache_config()
        if not cfg.cache_enabled:
            return None

        cache_key = _build_cache_key(
            intent, rewritten_query, cfg.kb_versions, cfg.tenant_id, cfg.gray_pct
        )

        if await NullCache.get(cache_key):
            _stats.record("null_hit")
            logger.debug("NullCache 命中（防穿透）: %s", cache_key[:16])
            return {"_layer": "null", "answer": "", "trace_id": ""}

        result = await L1Cache.get(cache_key)
        if result is not None:
            _stats.record("l1_hit")
            return result

        if query_vec is None:
            query_vec = _get_embedding(rewritten_query)

        if query_vec is not None:
            result = await L2Cache.get(query_vec)
            if result is not None:
                _stats.record("l2_hit")
                return result

        _stats.record("miss")
        return None

    @staticmethod
    async def set(
        intent: str,
        rewritten_query: str,
        value: dict[str, Any],
        query_vec: np.ndarray | None = None,
    ) -> None:
        """异步写入缓存（不阻塞响应）。

        Args:
            intent: 意图标签
            rewritten_query: 改写后的 query
            value: 缓存值（answer, trace_id, ...）
            query_vec: query 的 embedding 向量（可选，用于 L2）
        """
        cfg = get_cache_config()
        if not cfg.cache_enabled:
            return

        cache_key = _build_cache_key(
            intent, rewritten_query, cfg.kb_versions, cfg.tenant_id, cfg.gray_pct
        )

        answer = value.get("answer", "")
        if not answer:
            await NullCache.set(cache_key)
            return

        clean_value = {k: v for k, v in value.items() if not k.startswith("_")}
        clean_value["cached_at"] = time.time()

        await L1Cache.set(cache_key, clean_value, ttl=cfg.l1_ttl_seconds)

        if query_vec is None:
            query_vec = _get_embedding(rewritten_query)

        if query_vec is not None:
            await L2Cache.set(
                query_vec, rewritten_query, intent, clean_value, ttl=cfg.l2_ttl_seconds
            )

    @staticmethod
    async def set_async(*args: Any, **kwargs: Any) -> None:
        """fire-and-forget 异步写入（不阻塞调用方）。"""
        try:
            asyncio.create_task(SemanticCache.set(*args, **kwargs))
        except Exception as e:
            logger.warning("缓存异步写入失败: %s", e)

    @staticmethod
    def get_stats() -> dict[str, int | float]:
        """返回命中率统计。"""
        return _stats.snapshot()

    @staticmethod
    def reset_stats() -> None:
        """重置统计。"""
        _stats.reset()

    @staticmethod
    async def invalidate(intent: str, rewritten_query: str) -> None:
        """手动失效指定缓存。"""
        cfg = get_cache_config()
        cache_key = _build_cache_key(
            intent, rewritten_query, cfg.kb_versions, cfg.tenant_id, cfg.gray_pct
        )
        await L1Cache.invalidate(cache_key)

    @staticmethod
    async def invalidate_by_kb_version(subservice: str, new_version: str) -> None:
        """KB 版本更新时失效对应子服务缓存。

        更新 config 中的 kb_versions，旧缓存因 key 不匹配自动失效。
        """
        logger.info("KB 版本更新: %s → %s, 旧缓存自动失效", subservice, new_version)
