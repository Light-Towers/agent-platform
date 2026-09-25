"""Async adapter for agent_core.resilience.CircuitBreaker.

Wraps the sync upstream breaker with the async + fallback interface
the app expects, preserving backward-compatible state strings.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from agent_core.resilience import CircuitBreaker as _BaseBreaker

T = TypeVar("T")

# 兼容契约（保留一个小版本，WS-3）：runtime 对外常量沿用历史字符串（连字符风格
# "half-open"），与 state 属性返回值一致；内核真相源为 agent_core.resilience.STATE_*。
STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half-open"


class CircuitBreaker(_BaseBreaker):
    """Async-compatible circuit breaker with fallback.

    Extends agent_core.resilience.CircuitBreaker with:
    - recovery_seconds param alias (→ reset_timeout)
    - async call(fn, fallback) that returns fallback instead of raising
    - backward-compatible state strings ("half-open" not "half_open")
    - optional on_state_change callback for metrics/reporting
    - optional policy parameter (SlidingWindowPolicy / ConsecutiveFailurePolicy)

    状态读取经父类 ``resolved_state()``（计入冷却期的等效状态），不再直读
    父类私有字段（WS-3）。
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
        *,
        policy=None,
        on_state_change: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(
            policy=policy,
            failure_threshold=failure_threshold,
            reset_timeout=recovery_seconds,
            max_half_open_probe=1,
        )
        self._on_state_change = on_state_change
        self._last_state = self.resolved_state()

    @property
    def state(self) -> str:
        resolved = self.resolved_state()
        if resolved == self.HALF_OPEN:
            return STATE_HALF_OPEN
        return resolved

    def _report_transition(self) -> None:
        if self._on_state_change is None:
            return
        state = self.resolved_state()
        if state != self._last_state:
            self._on_state_change(self._last_state, state)
            self._last_state = state

    async def call(self, fn: Callable[[], Awaitable[T]], fallback: T | None = None) -> T:
        """Execute async fn; return fallback on open or error."""
        if not self.allow():
            self._report_transition()
            return fallback
        try:
            result = await fn()
        except Exception:
            self.record_failure()
            self._report_transition()
            return fallback
        self.record_success()
        self._report_transition()
        return result
