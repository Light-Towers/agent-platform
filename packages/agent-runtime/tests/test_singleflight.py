"""singleflight 单元测试：同 key 并发去重 + 结果共享。"""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.singleflight import singleflight


@pytest.mark.asyncio
async def test_singleflight_dedup_concurrent():
    """同 key 并发只执行一次 fn。"""
    call_count = 0

    async def slow_fn():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(
        singleflight("k1", slow_fn),
        singleflight("k1", slow_fn),
        singleflight("k1", slow_fn),
    )
    assert call_count == 1
    assert all(r == "result" for r in results)


@pytest.mark.asyncio
async def test_singleflight_different_keys_independent():
    """不同 key 独立执行。"""
    call_count = 0

    async def fn(val):
        nonlocal call_count
        call_count += 1
        return val

    r1, r2 = await asyncio.gather(
        singleflight("a", fn, "A"),
        singleflight("b", fn, "B"),
    )
    assert call_count == 2
    assert r1 == "A"
    assert r2 == "B"


@pytest.mark.asyncio
async def test_singleflight_passes_args_kwargs():
    """args/kwargs 透传给 fn。"""
    async def fn(a, b, c=0):
        return a + b + c

    result = await singleflight("sum", fn, 1, 2, c=3)
    assert result == 6


@pytest.mark.asyncio
async def test_singleflight_exception_propagates():
    """fn 抛异常时调用方收到异常。"""
    async def failing():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await singleflight("err", failing)
