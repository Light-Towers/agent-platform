"""显式关闭缓存时的 no-op 后端。

只由 ``CACHE_ENABLED=false`` 或 ``CACHE_BACKEND=disabled`` 选中；不是故障回退
目标（Valkey 不可用时仍走 Valkey 实现的 fail-open）。
"""

from __future__ import annotations

from typing import Any

from agent_core.cache import CacheHealth, CacheHit


class DisabledSemanticCache:
    """全部操作 no-op，健康态 ready=True（关闭是配置意图，不是故障）。"""

    enabled = False

    def __init__(self, scope: str) -> None:
        self._scope = scope

    async def startup(self) -> None:
        return None

    async def get(self, **_kwargs: Any) -> CacheHit | None:
        return None

    async def set(self, **_kwargs: Any) -> None:
        return None

    async def set_negative(self, **_kwargs: Any) -> None:
        return None

    async def invalidate(self, **_kwargs: Any) -> None:
        return None

    async def invalidate_namespace(self, **_kwargs: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def health(self) -> CacheHealth:
        return CacheHealth(backend="disabled", ready=True, degraded_reason=None, index=None)

    async def aclose(self) -> None:
        return None

    def get_stats(self) -> dict[str, Any]:
        # 计数器键集合必须与 Valkey 后端逐项对齐（parity 用例在 test_valkey_backend_wire.py:859；
        # 契约模型侧的双向判据在 tests/governance/test_cache_stats_contract.py，两件事不重叠：
        # 前者管"两个后端互相齐"，后者管"产出的计数都有字段、字段都有生产者"）。
        # 消费方是 `**get_stats()` 摊进监控事件 / `/health`，少一个键不会报错，只会在
        # CACHE_BACKEND 从 valkey 切成 disabled 时**静默换掉事件形状**——这属于"装了但没接上"
        # 同族，本仓的教训是它最难查。全为 0 是语义正确的：这个后端从不计数。
        return {
            "backend": "disabled",
            "scope": self._scope,
            "total": 0,
            "hit_rate": 0.0,
            "error": 0,
            "skipped_no_tenant": 0,
            "skipped_unsafe_tag": 0,
            "skipped_pii": 0,
            "dropped_writes": 0,
            "embedding_error": 0,
            "l2_unavailable": 0,
            "index_missing": 0,
        }

    def reset_stats(self) -> None:
        return None


__all__ = ["DisabledSemanticCache"]
