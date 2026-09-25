"""agent_core.resilience 单元测试。"""

import pytest

from agent_core.resilience import CircuitBreaker, retry, retry_async, timeout, validate_config


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------
def test_retry_succeeds_first_attempt():
    calls = 0

    @retry(max_attempts=3)
    def fn():
        nonlocal calls
        calls += 1
        return "ok"

    assert fn() == "ok"
    assert calls == 1


def test_retry_succeeds_after_failures():
    calls = 0

    @retry(max_attempts=3, backoff_base=0, sleep=lambda _: None)
    def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("transient")
        return "ok"

    assert fn() == "ok"
    assert calls == 3


def test_retry_exhausted_raises_last():
    calls = 0

    @retry(max_attempts=2, backoff_base=0, sleep=lambda _: None)
    def fn():
        nonlocal calls
        calls += 1
        raise ValueError(f"fail-{calls}")

    with pytest.raises(ValueError, match="fail-2"):
        fn()
    assert calls == 2


def test_retry_non_matching_exception_propagates():
    @retry(max_attempts=3, exceptions=ValueError, sleep=lambda _: None)
    def fn():
        raise TypeError("not retried")

    with pytest.raises(TypeError):
        fn()


# ---------------------------------------------------------------------------
# retry_async
# ---------------------------------------------------------------------------
async def _noop_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_retry_async_succeeds_first_attempt():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "ok"

    assert await retry_async(fn, max_attempts=3) == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_retry_async_succeeds_after_failures():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("transient")
        return "ok"

    assert await retry_async(fn, max_attempts=3, backoff_base=0, sleep=_noop_sleep) == "ok"
    assert calls == 3


@pytest.mark.asyncio
async def test_retry_async_exhausted_raises_last():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise ValueError(f"fail-{calls}")

    with pytest.raises(ValueError, match="fail-3"):
        await retry_async(fn, max_attempts=3, backoff_base=0, sleep=_noop_sleep)
    assert calls == 3


@pytest.mark.asyncio
async def test_retry_async_non_matching_exception_propagates():
    async def fn():
        raise TypeError("not retried")

    with pytest.raises(TypeError):
        await retry_async(fn, max_attempts=3, exceptions=ValueError, sleep=_noop_sleep)


@pytest.mark.asyncio
async def test_retry_async_passes_args_and_kwargs():
    async def add(a, b, *, c=0):
        return a + b + c

    assert await retry_async(add, 20, 22, max_attempts=2, c=0) == 42


@pytest.mark.asyncio
async def test_retry_async_backoff_sequence():
    sleeps: list[float] = []

    async def fn():
        raise ValueError("boom")

    async def fake_sleep(sec):
        sleeps.append(sec)

    with pytest.raises(ValueError):
        await retry_async(fn, max_attempts=3, backoff_base=0.5, backoff_factor=2.0, sleep=fake_sleep)
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_retry_async_on_retry_callback():
    seen: list[tuple] = []
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise ValueError("x")
        return "ok"

    async def cb(exc, attempt):
        seen.append((type(exc).__name__, attempt))

    assert await retry_async(fn, max_attempts=3, backoff_base=0, sleep=_noop_sleep, on_retry=cb) == "ok"
    assert calls == 2
    assert seen == [("ValueError", 1)]


@pytest.mark.asyncio
async def test_retry_async_invalid_max_attempts():
    async def fn():
        return 1

    with pytest.raises(ValueError, match="max_attempts"):
        await retry_async(fn, max_attempts=0)


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------
def test_timeout_completes_in_time():
    @timeout(seconds=1)
    def fn():
        return 42

    assert fn() == 42


def test_timeout_raises_on_exceed():
    import time

    @timeout(seconds=0.05)
    def fn():
        time.sleep(0.2)
        return "late"

    with pytest.raises(TimeoutError):
        fn()


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------
def test_breaker_closed_by_default():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=30)
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow() is True


def test_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=60)
    cb.record_failure()
    assert cb.state == CircuitBreaker.CLOSED
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    assert cb.allow() is False


def test_breaker_half_open_after_reset_timeout():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01, clock=lambda: 0)
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    cb._clock = lambda: 0.02
    assert cb.allow() is True
    assert cb.state == CircuitBreaker.HALF_OPEN


def test_breaker_half_open_success_closes():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01, clock=lambda: 0)
    cb.record_failure()
    cb._clock = lambda: 0.02
    cb.allow()
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED


def test_breaker_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01, clock=lambda: 0)
    cb.record_failure()
    cb._clock = lambda: 0.02
    cb.allow()
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN


def test_breaker_call_rejects_when_open():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
    cb.record_failure()
    with pytest.raises(RuntimeError, match="OPEN"):
        cb.call(lambda: "should not run")


def test_breaker_call_success_records():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
    result = cb.call(lambda x: x * 2, 21)
    assert result == 42
    assert cb.state == CircuitBreaker.CLOSED


# ---------------------------------------------------------------------------
# WS-3：并发安全 + resolved_state + STATE 常量
# ---------------------------------------------------------------------------
def test_breaker_state_constants_single_source():
    from agent_core.resilience import STATE_CLOSED, STATE_HALF_OPEN, STATE_OPEN

    assert CircuitBreaker.CLOSED == STATE_CLOSED == "closed"
    assert CircuitBreaker.OPEN == STATE_OPEN == "open"
    assert CircuitBreaker.HALF_OPEN == STATE_HALF_OPEN == "half_open"


def test_breaker_resolved_state_readonly():
    # OPEN 且冷却到期 → resolved_state 报 HALF_OPEN，但内部状态不突变
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01, clock=lambda: 0)
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    # 推进时钟超过冷却期（用可控 clock 重建）
    t = [0.0]
    cb2 = CircuitBreaker(failure_threshold=1, reset_timeout=10, clock=lambda: t[0])
    cb2.record_failure()
    t[0] = 20.0
    assert cb2.resolved_state() == CircuitBreaker.HALF_OPEN
    # 只读不突变：未经 allow() 前内部仍 OPEN
    assert cb2.state == CircuitBreaker.OPEN


def test_breaker_concurrent_half_open_probe_limited():
    """并发竞态（WS-3）：HALF_OPEN 时多线程并发 allow，探测数不超 max_half_open_probe。"""
    import threading

    t = [0.0]
    cb = CircuitBreaker(
        failure_threshold=1, reset_timeout=5, max_half_open_probe=1, clock=lambda: t[0]
    )
    cb.record_failure()  # → OPEN
    t[0] = 10.0  # 冷却到期 → 下一次 allow 转 HALF_OPEN

    allowed = []
    barrier = threading.Barrier(32)

    def _probe():
        barrier.wait()
        if cb.allow():
            allowed.append(1)

    threads = [threading.Thread(target=_probe) for _ in range(32)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # 32 个并发请求只允许 1 个成为 probe（锁保护下不竞态）
    assert len(allowed) == 1


def test_breaker_concurrent_record_failure_no_lost_updates():
    """并发 record_failure 不丢计数：N 线程各记一次，failure_threshold 内状态一致。"""
    import threading

    cb = CircuitBreaker(failure_threshold=100, reset_timeout=60)
    barrier = threading.Barrier(50)

    def _fail():
        barrier.wait()
        cb.record_failure()

    threads = [threading.Thread(target=_fail) for _ in range(50)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # 50 < 100 未熔断；再记 50 次应精确达到阈值转 OPEN（无丢失更新）
    assert cb.state == CircuitBreaker.CLOSED
    for _ in range(50):
        cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------
def test_validate_config_defaults():
    out = validate_config({"a": 1}, defaults={"b": 2})
    assert out == {"a": 1, "b": 2}


def test_validate_config_required_missing():
    with pytest.raises(ValueError, match="必填项"):
        validate_config({}, required=["api_key"])


def test_validate_config_type_check():
    with pytest.raises(TypeError, match="类型错误"):
        validate_config({"port": "abc"}, types={"port": int})


def test_validate_config_passes():
    out = validate_config(
        {"host": "localhost", "port": 8080},
        required=["host", "port"],
        types={"host": str, "port": int},
    )
    assert out == {"host": "localhost", "port": 8080}
