"""熔断器：closed -> open -> half-open 状态机。

连续失败达到阈值后打开熔断，恢复窗口内直接走 fallback，不再打下游；
窗口到期后放行一次试探（half-open），成功则复位，失败则重新计时。
"""

import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half-open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._state = STATE_CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        if self._state == STATE_OPEN and self._now() - self._opened_at >= self.recovery_seconds:
            return STATE_HALF_OPEN
        return self._state

    def _now(self) -> float:
        return time.monotonic()

    def record_success(self) -> None:
        self._failures = 0
        self._state = STATE_CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = STATE_OPEN
            self._opened_at = self._now()

    async def call(self, fn: Callable[[], Awaitable[T]], fallback: T | None = None) -> T:
        """执行 fn；熔断打开时不执行直接返回 fallback；fn 抛错时同样返回 fallback。"""
        if self.state == STATE_OPEN:
            return fallback
        try:
            result = await fn()
        except Exception:  # noqa: BLE001 熔断语义即吞错降级
            self.record_failure()
            return fallback
        self.record_success()
        return result
