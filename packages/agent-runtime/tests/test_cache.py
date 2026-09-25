"""cache.py 单元测试：语义缓存命中/未命中/阈值 + 后台写入 GC 防护。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime import cache


@pytest.fixture(autouse=True)
def _isolate_stats():
    cache.reset_stats()
    yield
    cache.reset_stats()


class _AsyncCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


def _make_pool(fetchone_return=None, execute_raises=False):
    row = MagicMock()
    row.fetchone = AsyncMock(return_value=fetchone_return)
    conn = MagicMock()
    if execute_raises:
        conn.execute = AsyncMock(side_effect=RuntimeError("db error"))
    else:
        conn.execute = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=_AsyncCtx(conn))
    return pool, conn


async def test_lookup_pool_none_returns_none():
    result = await cache.cache_lookup(None, [0.1, 0.2], threshold=0.5)
    assert result is None
    assert cache.get_stats()["miss"] == 1


async def test_lookup_hit_within_threshold():
    pool, _ = _make_pool(("cached-answer", 0.1))
    result = await cache.cache_lookup(pool, [0.1, 0.2], threshold=0.5)
    assert result == "cached-answer"
    assert cache.get_stats()["l2_hit"] == 1


async def test_lookup_miss_distance_above_threshold():
    pool, _ = _make_pool(("cached-answer", 0.8))
    result = await cache.cache_lookup(pool, [0.1], threshold=0.5)
    assert result is None
    assert cache.get_stats()["miss"] == 1


async def test_lookup_threshold_boundary_strict_less():
    pool, _ = _make_pool(("cached-answer", 0.5))
    result = await cache.cache_lookup(pool, [0.1], threshold=0.5)
    assert result is None
    assert cache.get_stats()["miss"] == 1


async def test_lookup_empty_table():
    pool, _ = _make_pool(None)
    result = await cache.cache_lookup(pool, [0.1], threshold=0.5)
    assert result is None
    assert cache.get_stats()["miss"] == 1


async def test_lookup_distance_none():
    pool, _ = _make_pool(("answer", None))
    result = await cache.cache_lookup(pool, [0.1], threshold=0.5)
    assert result is None
    assert cache.get_stats()["miss"] == 1


async def test_lookup_exception_degrades_to_miss():
    pool, _ = _make_pool(execute_raises=True)
    result = await cache.cache_lookup(pool, [0.1], threshold=0.5)
    assert result is None
    assert cache.get_stats()["miss"] == 1


async def test_store_pool_none_no_task():
    before = cache.pending_background_tasks()
    cache.cache_store(None, "q", "a", [0.1])
    await asyncio.sleep(0.01)
    assert cache.pending_background_tasks() == before


async def test_store_empty_answer_no_task():
    pool, _ = _make_pool()
    before = cache.pending_background_tasks()
    cache.cache_store(pool, "q", "", [0.1])
    await asyncio.sleep(0.01)
    assert cache.pending_background_tasks() == before


async def test_store_dispatches_background_task():
    pool, _ = _make_pool()
    cache.cache_store(pool, "question", "answer", [0.1])
    assert cache.pending_background_tasks() >= 1
    await asyncio.sleep(0.05)
    assert cache.pending_background_tasks() == 0


async def test_store_write_failure_silent():
    pool, _ = _make_pool(execute_raises=True)
    cache.cache_store(pool, "q", "a", [0.1])
    await asyncio.sleep(0.05)
    assert cache.pending_background_tasks() == 0


async def test_spawn_holds_reference():
    async def _long():
        await asyncio.sleep(100)

    task = cache.spawn_background(_long())
    assert cache.pending_background_tasks() >= 1
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_spawn_removes_on_done():
    async def _quick():
        await asyncio.sleep(0.01)

    cache.spawn_background(_quick())
    await asyncio.sleep(0.05)
    assert cache.pending_background_tasks() == 0


def test_reset_stats_clears():
    cache.reset_stats()
    s = cache.get_stats()
    assert s.get("total", 0) == 0
