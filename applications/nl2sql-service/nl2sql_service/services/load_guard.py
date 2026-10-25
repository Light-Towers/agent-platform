"""问数负载隔离（P1-5 / S-6）：应用侧并发闸 + 限流 + 每问 LLM 调用计数入口。

Doris 侧 workload group（P1-5）管不到应用层这条：本服务自身要有并发上限与
限流，否则 LLM 生成的 ad-hoc SQL 会在应用侧无限并发（成本放大 + DoS，S-6）。

- **并发闸**：`asyncio.Semaphore`，超过 `query_max_concurrency` 的请求排队，
  排队超过 `acquire_timeout` 直接拒绝（快失败比把请求挂死好——连接池配额
  也扛不住无限排队）。
- **限流**：复用 agent-core 现成 `SlidingWindowRateLimiter`（不新建，§方案
  "随 P1-5 用现成件"），按租户/用户维度限每分钟请求数。
- **LLM 调用计数**：每问 LLM 调用进 trace（S-6），由节点侧 `bump_llm_calls`
  累加，LoadGuard 只提供计数器的原子 helper。

全 0 默认 = 关闭（老部署逐字节一致）：`query_max_concurrency=0` 且
`query_rate_limit_per_min=0` 时不设任何闸。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter
from agent_core.logging import get_logger

logger = get_logger(__name__)


class LoadRejected(Exception):
    """并发闸/限流拒绝。message 是对外可读原因。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class LoadGuardConfig:
    max_concurrency: int = 0  # 0 = 不限并发
    rate_limit_per_min: int = 0  # 0 = 不限流
    acquire_timeout: float = 5.0  # 并发闸排队上限（秒）；超时即拒绝
    rate_window_seconds: int = 60


class LoadGuard:
    """进程内单例（lifespan 建一个，挂 app.state / context）。"""

    def __init__(self, config: LoadGuardConfig) -> None:
        self._config = config
        self._sem = asyncio.Semaphore(config.max_concurrency) if config.max_concurrency > 0 else None
        self._limiter = (
            SlidingWindowRateLimiter(max_requests=config.rate_limit_per_min, window_seconds=config.rate_window_seconds)
            if config.rate_limit_per_min > 0
            else None
        )

    def check_rate(self, key: str) -> None:
        """限流检查（同步，进图前调用）；超限抛 LoadRejected。"""
        if self._limiter is None:
            return
        allowed, retry_after = self._limiter.allow(key)
        if not allowed:
            raise LoadRejected(f"请求过于频繁，请 {retry_after} 秒后重试")

    def slot(self, key: str) -> "_Slot":
        """返回异步上下文管理器：限流检查 + 并发闸占用，退出释放。

        用法：`async with guard.slot(tenant_or_user): await graph.ainvoke(...)`
        """
        return _Slot(self, key)


class _Slot:
    def __init__(self, guard: LoadGuard, key: str) -> None:
        self._guard = guard
        self._key = key
        self._acquired = False

    async def __aenter__(self) -> "_Slot":
        self._guard.check_rate(self._key)
        sem = self._guard._sem
        if sem is None:
            return self
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._guard._config.acquire_timeout)
        except asyncio.TimeoutError as exc:
            raise LoadRejected("系统繁忙（并发问数已达上限），请稍后重试") from exc
        self._acquired = True
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._acquired:
            self._guard._sem.release()
            self._acquired = False


def bump_llm_calls(state: dict) -> int:
    """节点侧 LLM 调用计数 +1，返回新值（写回 state['llm_calls']）。

    每个调 `llm.invoke` 的节点在拿到结果后调用一次——并发下各自基于入参
    state 累加，图合并时取最后写入者（同一轮内节点串行，计数不丢）。
    """
    return int(state.get("llm_calls", 0)) + 1


def now_ms() -> float:
    return time.perf_counter() * 1000


__all__ = ["LoadGuard", "LoadGuardConfig", "LoadRejected", "bump_llm_calls"]
