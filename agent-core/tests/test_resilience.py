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
