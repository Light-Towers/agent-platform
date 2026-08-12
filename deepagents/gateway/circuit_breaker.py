"""熔断器 + 重试：tenacity 驱动，子服务超时降级到 fallback。

复用 tools/_timeout.py 已有超时 + tenacity 9.1.4（requirements.txt:113）。
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from enum import Enum
from threading import Lock
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_FAILURE_THRESHOLD", "5"))
_RECOVERY_TIMEOUT = int(os.getenv("CIRCUIT_RECOVERY_TIMEOUT", "30"))


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """熔断器：失败数超阈值 → OPEN（拒绝请求），恢复超时后 → HALF_OPEN（试探）。"""

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = _FAILURE_THRESHOLD,
        recovery_timeout: int = _RECOVERY_TIMEOUT,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    def _can_execute(self) -> bool:
        """检查是否允许执行。"""
        import time

        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("熔断器 %s → HALF_OPEN", self.name)
                    return True
                return False
            return True

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("熔断器 %s → CLOSED（恢复）", self.name)
            self._failure_count = 0

    def _on_failure(self) -> None:
        import time

        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("熔断器 %s → OPEN（半开试探失败）", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("熔断器 %s → OPEN（失败 %d 次）", self.name, self._failure_count)

    async def call(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        fallback: Callable[..., Awaitable[Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """通过熔断器调用 async fn，失败时走 fallback。"""
        if not self._can_execute():
            logger.warning("熔断器 %s OPEN，请求被拒绝", self.name)
            if fallback:
                return await fallback(*args, **kwargs)
            raise CircuitBreakerOpenError(f"熔断器 {self.name} 处于 OPEN 状态")

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            if fallback:
                logger.warning("熔断器 %s 调用失败，走 fallback: %s", self.name, e)
                return await fallback(*args, **kwargs)
            raise


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常。"""


_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """获取或创建命名熔断器。"""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


def get_circuit_stats() -> dict[str, str]:
    """返回所有熔断器状态。"""
    return {name: cb.state.value for name, cb in _breakers.items()}
