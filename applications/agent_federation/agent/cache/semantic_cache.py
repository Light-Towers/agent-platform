"""联邦语义缓存入口：委托统一 Valkey 实现（ADR-0013 C）。

保留原公开签名，内部只做上下文注入（scope=federation、租户/KB/灰度）；
L1/L2/负缓存/TTL/失效/fail-open 均在 ``agent_runtime.cache`` 单一实现里。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from agent_core.cache import build_cache_key
from agent_core.logging import get_logger
from agent_runtime.cache import get_cache

from agent.cache.config import get_cache_context, set_kb_version

logger = get_logger(__name__)

_pending_writes: set[asyncio.Task] = set()


class SemanticCache:
    """联邦语义缓存门面。"""

    @staticmethod
    def _backend():
        return get_cache("federation")

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._backend().enabled

    @staticmethod
    def build_key(intent: str, rewritten_query: str) -> str:
        """singleflight 去重 key（含租户/KB/灰度，跨租户不共享在途结果）。"""
        ctx = get_cache_context()
        return build_cache_key(
            intent,
            rewritten_query,
            ctx.kb_versions,
            ctx.tenant_id,
            ctx.gray_pct,
        )

    @staticmethod
    async def get(
        intent: str,
        rewritten_query: str,
        query_vec: list[float] | None = None,
    ) -> dict[str, Any] | None:
        ctx = get_cache_context()
        backend = get_cache("federation")
        if not backend.enabled:
            return None
        hit = await backend.get(
            tenant_id=ctx.tenant_id,
            intent=intent,
            rewritten_query=rewritten_query,
            kb_versions=ctx.kb_versions,
            gray_pct=ctx.gray_pct,
            embedding=query_vec,
        )
        if hit is None:
            return None
        value = dict(hit.value)
        value.setdefault("_layer", hit.layer)
        if hit.distance is not None:
            value.setdefault("_distance", hit.distance)
        if hit.similarity is not None:
            value.setdefault("_similarity", hit.similarity)
        return value

    @staticmethod
    async def set(
        intent: str,
        rewritten_query: str,
        value: dict[str, Any],
        query_vec: list[float] | None = None,
    ) -> None:
        ctx = get_cache_context()
        backend = get_cache("federation")
        if not backend.enabled:
            return
        answer = value.get("answer", "")
        if not answer:
            await backend.set_negative(
                tenant_id=ctx.tenant_id,
                intent=intent,
                rewritten_query=rewritten_query,
                kb_versions=ctx.kb_versions,
                gray_pct=ctx.gray_pct,
            )
            return
        clean_value = {k: v for k, v in value.items() if not k.startswith("_")}
        clean_value["cached_at"] = time.time()
        await backend.set(
            tenant_id=ctx.tenant_id,
            intent=intent,
            rewritten_query=rewritten_query,
            value=clean_value,
            kb_versions=ctx.kb_versions,
            gray_pct=ctx.gray_pct,
            embedding=query_vec,
        )

    @staticmethod
    async def set_async(*args: Any, **kwargs: Any) -> None:
        """fire-and-forget 写入（后端内部还有有界队列，双保险不阻塞调用方）。"""
        try:
            task = asyncio.create_task(SemanticCache.set(*args, **kwargs))
            _pending_writes.add(task)
            task.add_done_callback(_pending_writes.discard)
        except Exception as e:  # noqa: BLE001 - 缓存写入失败不得影响主链路
            logger.warning("缓存异步写入失败: %s", e)

    @staticmethod
    def get_stats() -> dict[str, Any]:
        return get_cache("federation").get_stats()

    @staticmethod
    def reset_stats() -> None:
        get_cache("federation").reset_stats()

    @staticmethod
    async def invalidate(intent: str, rewritten_query: str) -> None:
        ctx = get_cache_context()
        await get_cache("federation").invalidate(
            tenant_id=ctx.tenant_id,
            intent=intent,
            rewritten_query=rewritten_query,
            kb_versions=ctx.kb_versions,
            gray_pct=ctx.gray_pct,
        )

    @staticmethod
    async def invalidate_by_kb_version(subservice: str, new_version: str) -> None:
        """KB 版本更新：改上下文（新 key 天然不命中旧值）+ 递增租户 epoch。"""
        set_kb_version(subservice, new_version)
        ctx = get_cache_context()
        await get_cache("federation").invalidate_namespace(tenant_id=ctx.tenant_id)
        logger.info("KB 版本更新: %s → %s，联邦缓存命名空间已失效", subservice, new_version)
