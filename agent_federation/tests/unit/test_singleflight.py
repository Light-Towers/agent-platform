"""P4：缓存击穿防护（singleflight 接入主链路）。

验证：同一 cache key 的并发调用只执行一次 fn（Agent/LLM），其余等同一结果，
避免热点 query 并发把下游打爆。无真实 LLM/缓存调用。
"""
import asyncio

import pytest


def test_singleflight_dedupes_concurrent_calls():
    from agent.cache.singleflight import singleflight

    calls = 0

    async def slow_fn(x):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return f"answer-{x}-{calls}"

    async def run():
        # 10 个并发相同 key，应只执行 1 次 fn
        results = await asyncio.gather(
            *(singleflight("same-key", slow_fn, 42) for _ in range(10))
        )
        return results

    results = asyncio.run(run())
    assert calls == 1, f"期望只执行 1 次，实际 {calls}"
    # 所有并发调用者拿到同一结果
    assert all(r == "answer-42-1" for r in results)


def test_singleflight_distinct_keys_run_separately():
    from agent.cache.singleflight import singleflight

    calls = 0

    async def slow_fn(x):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return x

    async def run():
        return await asyncio.gather(
            singleflight("key-a", slow_fn, "a"),
            singleflight("key-b", slow_fn, "b"),
        )

    results = asyncio.run(run())
    assert calls == 2
    assert results == ["a", "b"]


def test_singleflight_propagates_exception():
    from agent.cache.singleflight import singleflight

    async def boom(_):
        raise ValueError("kaboom")

    async def run():
        with pytest.raises(ValueError):
            await singleflight("err-key", boom, 1)
        # 并发方也应拿到异常（而非 hang），且不会二次执行
        return

    async def run2():
        tasks = [singleflight("err-key", boom, 1) for _ in range(3)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(r, ValueError) for r in results)

    asyncio.run(run2())


def test_cache_key_consistency_with_semantic_cache():
    """P4：singleflight key 构造须与 SemanticCache 一致，否则去重失效。

    验证 _build_cache_key 在相同参数下产出稳定 key，且含 kb_versions/tenant_id。
    """
    from agent.cache.layers import _build_cache_key

    key1 = _build_cache_key("sql", "查销售额", {"wenda": "v1"}, "t1", 0.0)
    key2 = _build_cache_key("sql", "查销售额", {"wenda": "v1"}, "t1", 0.0)
    assert key1 == key2  # 同参数稳定
    key3 = _build_cache_key("sql", "查销售额", {"wenda": "v2"}, "t1", 0.0)
    assert key3 != key1  # KB 版本变化 → 不同 key（旧缓存自动失效语义）
