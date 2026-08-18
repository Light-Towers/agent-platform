"""P3：子 Agent 委派熔断器。

为远程子服务（AsyncSubAgent / httpx 回退）提供 per-agent 熔断能力，
避免单个子服务持续故障把主管线程拖垮。配合 `agent.config.healthy`
（健康探活），形成「探活短路 + 熔断 + 本地 fallback」三级防护。

状态机（借鉴 agent-core 已有 circuit-breaker 语义）：
    CLOSED  --失败率超阈值-->  OPEN  --冷却到期-->  HALF_OPEN
    OPEN    --探测成功----->  CLOSED
    HALF_OPEN --探测失败--->  OPEN
    HALF_OPEN --探测成功--->  CLOSED（连续成功清零计数）

阈值与窗口均可通过环境变量调参，默认值偏保守（生产级）。
"""

from __future__ import annotations

import asyncio
import time

from agent_core.logging import get_logger

from agent.agent.metrics import record_circuit_state

logger = get_logger(__name__)

# 失败率阈值：窗口内失败占比超过该值则熔断。
_CB_FAILURE_RATIO = float(__import__("os").getenv("CB_FAILURE_RATIO", "0.5"))
# 最小请求数：窗口内请求数低于该值不触发熔断（避免偶发失败误伤）。
_CB_MIN_REQUESTS = int(__import__("os").getenv("CB_MIN_REQUESTS", "5"))
# 滑动窗口大小（请求数）。
_CB_WINDOW_SIZE = int(__import__("os").getenv("CB_WINDOW_SIZE", "20"))
# OPEN 状态冷却时间（秒），到期进入 HALF_OPEN 放行探测。
_CB_COOLDOWN_SECONDS = float(__import__("os").getenv("CB_COOLDOWN_SECONDS", "30"))
# HALF_OPEN 允许的探测请求数（连续成功则恢复）。
_CB_HALF_OPEN_PROBES = int(__import__("os").getenv("CB_HALF_OPEN_PROBES", "3"))


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """单个子服务（按 graph_id/name）的熔断器。

    线程/协程安全：所有状态变更均在 asyncio.Lock 保护下。
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
        self.failure_ratio = failure_ratio
        self.min_requests = min_requests
        self.window_size = window_size
        self.cooldown_seconds = cooldown_seconds
        self.half_open_probes = half_open_probes

        self._state = CircuitState.CLOSED
        self._opened_at: float = 0.0
        self._successes: list[float] = []  # 滑动窗口成功时间戳
        self._failures: list[float] = []  # 滑动窗口失败时间戳
        self._half_open_successes = 0
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return time.monotonic()

    def _transition(self, new_state: str) -> None:
        """统一状态转换入口：更新内部状态 + 记录指标/上报（P3 可观测性）。"""
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        record_circuit_state(self.name, new_state)
        logger.info("[circuit:%s] state %s -> %s", self.name, old, new_state)

    def _trim(self) -> None:
        """按窗口大小裁剪滑动窗口（保留最近 window_size 次结果）。"""
        for bucket in (self._successes, self._failures):
            while len(bucket) > self.window_size:
                bucket.pop(0)

    def state(self) -> str:
        return self._state

    async def allow(self) -> bool:
        """是否允许本次委派。OPEN 且冷却未到期 -> 拒绝；冷却到期 -> 转 HALF_OPEN。"""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._now() - self._opened_at >= self.cooldown_seconds:
                    self._half_open_successes = 0
                    self._transition(CircuitState.HALF_OPEN)
                    return True
                return False
            return True

    async def record_success(self) -> None:
        async with self._lock:
            now = self._now()
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_probes:
                    self._successes = []
                    self._failures = []
                    self._transition(CircuitState.CLOSED)
                return
            self._successes.append(now)
            self._trim()
            self._evaluate_locked()

    async def record_failure(self) -> None:
        async with self._lock:
            now = self._now()
            if self._state == CircuitState.HALF_OPEN:
                self._opened_at = now
                self._half_open_successes = 0
                self._transition(CircuitState.OPEN)
                return
            self._failures.append(now)
            self._trim()
            self._evaluate_locked()

    def _evaluate_locked(self) -> None:
        """在持锁状态下评估是否触发熔断（仅 CLOSED 态）。"""
        if self._state != CircuitState.CLOSED:
            return
        total = len(self._successes) + len(self._failures)
        if total < self.min_requests:
            return
        failures = len(self._failures)
        if failures / total >= self.failure_ratio:
            self._opened_at = self._now()
            self._transition(CircuitState.OPEN)


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
