"""Memory 衰减管理：TTL 过期 + 容量上限 LRU 淘汰。

防止 Episodic Memory 无限膨胀——定期调用 cleanup() 清理：
1. 超过 max_age_seconds 的 Episode → 删除（过时经验）
2. 仍超 max_size → 按 importance 最低淘汰（低价值经验）

可作为 post_execution_hook 挂载（每次执行后检查），
也可由定时任务触发（如每小时一次）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agent_runtime.episodic_memory import EpisodicStore
from agent_runtime.trajectory.models import TrajectoryRecord

logger = logging.getLogger(__name__)


class MemoryDecayManager:
    """Episodic Memory 衰减管理：TTL 过期 + LRU 淘汰。"""

    def __init__(
        self,
        store: EpisodicStore,
        max_age_seconds: float = 30 * 24 * 3600,
        max_size: int = 10000,
        cleanup_interval: int = 50,
    ) -> None:
        self._store = store
        self._max_age = max_age_seconds
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval
        self._count = 0

    async def __call__(self, trajectory: TrajectoryRecord, runtime: Any) -> None:
        """作为 post_execution_hook：每 cleanup_interval 次执行触发一次清理。"""
        self._count += 1
        if self._count < self._cleanup_interval:
            return
        self._count = 0
        await self.cleanup()

    async def cleanup(self) -> tuple[int, int]:
        """清理过期 + 超容量，返回 (expired_count, evicted_count)。"""
        now = time.time()
        all_eps = await self._store.list_all(limit=1000000)

        expired_count = 0
        for ep in all_eps:
            if now - ep.created_at > self._max_age:
                await self._store.delete(ep.episode_id)
                expired_count += 1

        remaining = await self._store.list_all(limit=1000000)
        evicted_count = 0
        if len(remaining) > self._max_size:
            remaining.sort(key=lambda e: e.importance)
            to_evict = remaining[: len(remaining) - self._max_size]
            for ep in to_evict:
                await self._store.delete(ep.episode_id)
                evicted_count += 1

        if expired_count > 0 or evicted_count > 0:
            logger.info(
                "memory decay: expired=%d evicted=%d", expired_count, evicted_count
            )
        return expired_count, evicted_count


__all__ = ["MemoryDecayManager"]
