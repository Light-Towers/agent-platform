# -*- coding: utf-8 -*-
"""语义缓存共享工具：命中率统计。

框架无关内核，仅依赖 stdlib。各后端（PostgreSQL / Valkey）各自实例化使用。
"""

from __future__ import annotations


class CacheStats:
    """命中率统计（asyncio 单线程语义，无需加锁）。

    用法::

        stats = CacheStats()
        stats.record("l1_hit")      # 记录 L1 命中
        stats.record("miss")        # 记录未命中
        stats.snapshot()            # → {"l1_hit": 1, "miss": 1, "total": 2, "hit_rate": 0.5}
    """

    __slots__ = ("_counts",)

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def record(self, layer: str) -> None:
        """记录一次查询结果。

        :param layer: ``l1_hit`` / ``l2_hit`` / ``null_hit`` / ``miss``
        """
        self._counts[layer] = self._counts.get(layer, 0) + 1
        self._counts["total"] = self._counts.get("total", 0) + 1

    def snapshot(self) -> dict[str, int | float]:
        """返回当前统计快照（含 hit_rate）。"""
        total = self._counts.get("total", 0) or 1
        hits = sum(self._counts.get(k, 0) for k in ("l1_hit", "l2_hit", "null_hit"))
        return {**self._counts, "hit_rate": round(hits / total, 4)}

    def reset(self) -> None:
        """清空统计。"""
        self._counts.clear()


__all__ = ["CacheStats"]
