"""Async adapter for agent_core.resilience.CircuitBreaker.

Wraps the sync upstream breaker with the async + fallback interface
the app expects, preserving backward-compatible state strings.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from agent_core.resilience import CircuitBreaker as _BaseBreaker

T = TypeVar("T")

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half-open"


class CircuitBreaker(_BaseBreaker):
    """Async-compatible circuit breaker with fallback.

    Extends agent_core.resilience.CircuitBreaker with:
    - recovery_seconds param alias (→ reset_timeout)
    - async call(fn, fallback) that returns fallback instead of raising
    - backward-compatible state strings ("half-open" not "half_open")
    """

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 30.0) -> None:
        super().__init__(failure_threshold=failure_threshold, reset_timeout=recovery_seconds)

    @property
    def state(self) -> str:
        if (
            self._state == self.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self._reset_timeout
        ):
            return STATE_HALF_OPEN
        if self._state == self.HALF_OPEN:
            return STATE_HALF_OPEN
        return self._state

    async def call(self, fn: Callable[[], Awaitable[T]], fallback: T | None = None) -> T:
        """Execute async fn; return fallback on open or error."""
        if not self.allow():
            return fallback
        try:
            result = await fn()
        except Exception:  # noqa: BLE001 熔断语义即吞错降级
            self.record_failure()
            return fallback
        self.record_success()
        return result
