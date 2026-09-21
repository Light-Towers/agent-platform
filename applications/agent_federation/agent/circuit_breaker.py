"""P3：子 Agent 委派熔断器（F-S1-04 收口）。

核心引擎复用 agent_core.resilience.CircuitBreaker(SlidingWindowPolicy)，
async 适配 + 指标上报经 agent_runtime.circuit_breaker.CircuitBreaker(on_state_change=) 注入。

状态机（与 agent_core.resilience.SlidingWindowPolicy 一致）：
    CLOSED  --失败率超阈值-->  OPEN  --冷却到期-->  HALF_OPEN
    OPEN    --探测成功----->  CLOSED
    HALF_OPEN --探测失败--->  OPEN
    HALF_OPEN --探测成功--->  CLOSED（连续成功清零计数）

阈值与窗口均可通过环境变量调参，默认值偏保守（生产级）。
"""

from __future__ import annotations

import asyncio

from agent_core.logging import get_logger
from agent_core.resilience import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    SlidingWindowPolicy,
)
from agent_runtime.circuit_breaker import CircuitBreaker as _RuntimeBreaker

from agent.metrics import record_circuit_state

logger = get_logger(__name__)

_CB_FAILURE_RATIO = float(__import__("os").getenv("CB_FAILURE_RATIO", "0.5"))
_CB_MIN_REQUESTS = int(__import__("os").getenv("CB_MIN_REQUESTS", "5"))
_CB_WINDOW_SIZE = int(__import__("os").getenv("CB_WINDOW_SIZE", "20"))
_CB_COOLDOWN_SECONDS = float(__import__("os").getenv("CB_COOLDOWN_SECONDS", "30"))
_CB_HALF_OPEN_PROBES = int(__import__("os").getenv("CB_HALF_OPEN_PROBES", "3"))


class CircuitState:
    CLOSED = STATE_CLOSED
    OPEN = STATE_OPEN
    HALF_OPEN = STATE_HALF_OPEN


class CircuitBreaker(_RuntimeBreaker):
    """单个子服务（按 graph_id/name）的熔断器（async + 指标上报）。

    复用 agent_runtime.circuit_breaker.CircuitBreaker(async 适配 + on_state_change 回调)，
    策略用 SlidingWindowPolicy（与 agent_core.resilience 既有实现一致，勿新建）。
    """

    def __init__(
        self,
        name: str,
        failure_ratio: float = _CB_FAILURE_RATIO,
        min_requests: int = _CB_MIN_REQUESTS,
        window_size: int = _CB_WINDOW_SIZE,
        cooldown_seconds: float = _CB_COOLDOWN_SECONDS,
        half_open_probes: int = _CB_HALF_OPEN_PROBES,
    ) -> None:
        self.name = name
        policy = SlidingWindowPolicy(
            failure_ratio=failure_ratio,
            min_requests=min_requests,
            window_size=window_size,
            cooldown_seconds=cooldown_seconds,
            half_open_probes=half_open_probes,
        )

        def _on_state_change(old: str, new: str) -> None:
            record_circuit_state(self.name, new)
            logger.info("[circuit:%s] state %s -> %s", self.name, old, new)

        super().__init__(policy=policy, on_state_change=_on_state_change)

    async def allow(self) -> bool:
        allowed = super().allow()
        self._report_transition()
        return allowed

    async def record_success(self) -> None:
        super().record_success()
        self._report_transition()

    async def record_failure(self) -> None:
        super().record_failure()
        self._report_transition()


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = asyncio.Lock()


async def get_breaker(name: str) -> CircuitBreaker:
    """按 name 获取（或新建）熔断器单例。"""
    async with _breakers_lock:
        br = _breakers.get(name)
        if br is None:
            br = CircuitBreaker(name)
            _breakers[name] = br
        return br


def get_breaker_sync(name: str) -> CircuitBreaker:
    """同步获取（构造期/Mock 场景用），不保证并发安全。"""
    br = _breakers.get(name)
    if br is None:
        br = CircuitBreaker(name)
        _breakers[name] = br
    return br
