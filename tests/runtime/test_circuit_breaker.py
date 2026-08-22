import asyncio

from agent_runtime.circuit_breaker import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    CircuitBreaker,
)


async def _failing():
    raise RuntimeError("downstream down")


async def test_breaker_opens_after_threshold_and_short_circuits():
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60)
    calls = 0

    async def counting_fail():
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    assert await breaker.call(counting_fail, fallback="fb") == "fb"
    assert await breaker.call(counting_fail, fallback="fb") == "fb"
    assert breaker.state == STATE_OPEN
    # 熔断打开后不再打下游
    assert await breaker.call(counting_fail, fallback="fb") == "fb"
    assert calls == 2


async def test_breaker_half_open_recovery():
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=0.02)
    await breaker.call(_failing, fallback=None)
    assert breaker.state == STATE_OPEN
    await asyncio.sleep(0.03)
    assert breaker.state == STATE_HALF_OPEN

    async def ok():
        return "recovered"

    assert await breaker.call(ok, fallback=None) == "recovered"
    assert breaker.state == STATE_CLOSED
