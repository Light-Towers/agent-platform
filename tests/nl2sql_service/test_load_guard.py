"""负载隔离（P1-5/S-6）：并发闸 + 限流 + 每问 LLM 调用计数。"""

from __future__ import annotations

import asyncio

import pytest

from nl2sql_service.services.load_guard import (
    LoadGuard,
    LoadGuardConfig,
    LoadRejected,
    bump_llm_calls,
)


class TestDisabledByDefault:
    def test_all_zero_config_has_no_gate(self):
        guard = LoadGuard(LoadGuardConfig(max_concurrency=0, rate_limit_per_min=0))
        assert guard._sem is None
        assert guard._limiter is None

    async def test_disabled_slot_passes_through(self):
        guard = LoadGuard(LoadGuardConfig(max_concurrency=0, rate_limit_per_min=0))
        async with guard.slot("k"):
            pass  # 不抛即通过


class TestConcurrency:
    async def test_over_limit_rejected_after_timeout(self):
        guard = LoadGuard(LoadGuardConfig(max_concurrency=1, acquire_timeout=0.05))
        async with guard.slot("k"):
            # 第二个请求在 timeout 内拿不到槽 → 拒绝
            with pytest.raises(LoadRejected):
                async with guard.slot("k"):
                    pass

    async def test_slot_released_after_exit(self):
        guard = LoadGuard(LoadGuardConfig(max_concurrency=1, acquire_timeout=0.5))
        async with guard.slot("k"):
            pass
        # 退出后槽已释放，可再进
        async with guard.slot("k"):
            pass

    async def test_parallel_within_limit_ok(self):
        guard = LoadGuard(LoadGuardConfig(max_concurrency=3, acquire_timeout=0.5))

        async def work():
            async with guard.slot("k"):
                await asyncio.sleep(0.01)

        await asyncio.gather(work(), work(), work())  # 3 并发内不拒绝


class TestRateLimit:
    def test_over_rate_rejected(self):
        guard = LoadGuard(LoadGuardConfig(rate_limit_per_min=2, rate_window_seconds=60))
        guard.check_rate("t1")
        guard.check_rate("t1")
        with pytest.raises(LoadRejected):
            guard.check_rate("t1")

    def test_rate_scoped_per_key(self):
        guard = LoadGuard(LoadGuardConfig(rate_limit_per_min=1, rate_window_seconds=60))
        guard.check_rate("t1")
        guard.check_rate("t2")  # 不同 key 互不影响
        with pytest.raises(LoadRejected):
            guard.check_rate("t1")


class TestBumpLlmCalls:
    def test_increments_from_state(self):
        assert bump_llm_calls({}) == 1
        assert bump_llm_calls({"llm_calls": 3}) == 4


async def test_query_service_graceful_on_load_reject():
    """LoadGuard 拒绝时 query() 返回可读错误 + fallback，不抛 500。"""
    from unittest.mock import MagicMock

    from nl2sql_service.services.load_guard import LoadGuard, LoadGuardConfig
    from nl2sql_service.services.query_service import QueryService

    guard = LoadGuard(LoadGuardConfig(rate_limit_per_min=1, rate_window_seconds=60))
    ctx = MagicMock()
    ctx.datasources = None
    ctx.load_guard = guard
    ctx.table_stats = []
    svc = QueryService(graph=MagicMock(), context=ctx, llm=MagicMock())
    r1 = await svc.query("q", tenant_id="t1")
    r2 = await svc.query("q", tenant_id="t1")
    assert r1["fallback"] is True  # graph 是 MagicMock，ainvoke 返回 MagicMock → 走 _build_response
    assert "频繁" in r2["error"] and r2["fallback"] is True
