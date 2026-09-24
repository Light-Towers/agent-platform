"""singleflight 单元测试：同 key 并发去重 + 结果共享。"""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.singleflight import _cleanup, _inflight_results, _locks, _refs, singleflight


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


@pytest.mark.asyncio
async def test_cleanup_skipped_when_refs_positive():
    """P2-2 回归：_refs>0 时 _cleanup 不得删除 lock/result。"""
    key = "race_test"
    lock = asyncio.Lock()
    _locks[key] = lock
    _refs[key] = 2  # 模拟还有等待者
    _inflight_results[key] = "cached"

    # 调用 cleanup，应因 refcount>0 而跳过
    _cleanup(key, lock)
    assert key in _locks, "_cleanup 不应在 refs>0 时删除 lock"
    assert key in _inflight_results

    # 清理测试状态
    _locks.pop(key, None)
    _refs.pop(key, None)
    _inflight_results.pop(key, None)


@pytest.mark.asyncio
async def test_cleanup_skipped_on_lock_identity_mismatch():
    """P2-2 回归：lock 已被替换时，旧 callback 不得删除新 lock。"""
    key = "mismatch_test"
    old_lock = asyncio.Lock()
    new_lock = asyncio.Lock()
    _locks[key] = new_lock  # 已被替换
    _refs[key] = 0
    _inflight_results[key] = "new_result"

    _cleanup(key, old_lock)  # 传入旧的 lock对象
    assert key in _locks, "_cleanup 不应删除身份不匹配的 lock"
    assert _locks[key] is new_lock

    # 清理
    _locks.pop(key, None)
    _refs.pop(key, None)
    _inflight_results.pop(key, None)


@pytest.mark.asyncio
async def test_singleflight_refcount_after_completion():
    """singleflight 正常完成后 refs 应归零，允许后续 cleanup。"""
    key = "ref_count_test"

    async def fn():
        return 42

    result = await singleflight(key, fn)
    assert result == 42
    # fn 完成后 refs 应已减到 0
    assert _refs.get(key, 0) == 0
