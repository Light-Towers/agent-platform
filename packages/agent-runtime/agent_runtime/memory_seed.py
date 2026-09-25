"""种子记忆：冷启动时预置经验。

新部署/新租户没有历史 Episode——recall 返回空，Agent 无法从经验中受益。
MemorySeeder 提供预置种子 Episode 的能力，使冷启动时也有基础经验可召回。
"""

from __future__ import annotations

import logging

from agent_runtime.episodic_memory import Episode, EpisodicMemory

logger = logging.getLogger(__name__)


class MemorySeeder:
    """种子记忆：冷启动时预置经验。

    用法：
    ```
    seeder = MemorySeeder(episodic_memory)
    await seeder.seed([
        Episode(episode_id="seed-1", task_summary="常见任务", ...),
        ...
    ])
    ```
    """

    def __init__(self, episodic_memory: EpisodicMemory) -> None:
        self._ep = episodic_memory

    async def seed(self, episodes: list[Episode]) -> int:
        """预置种子 Episode，跳过已存在的，返回新增数量。"""
        count = 0
        for ep in episodes:
            existing = await self._ep._store.get(ep.episode_id)
            if existing is not None:
                continue
            await self._ep._store.save(ep)
            count += 1
        if count > 0:
            logger.info("seeded %d episodes", count)
        return count


__all__ = ["MemorySeeder"]
