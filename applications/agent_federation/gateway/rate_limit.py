"""Token bucket 限流：按 tenant_id 隔离，超限返回 429。

复用 SecurityGuardsMiddleware 已有限流，这里是应用层 LLM 调用限流。
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock

from agent_core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_RPM = int(os.getenv("RATE_LIMIT_RPM", "60"))
_DEFAULT_BURST = int(os.getenv("RATE_LIMIT_BURST", "10"))


class TokenBucket:
    """Token bucket 算法：RPM（每分钟请求数）+ burst（突发容量）。"""

    def __init__(self, rpm: int = _DEFAULT_RPM, burst: int = _DEFAULT_BURST):
        self.rpm = rpm
        self.capacity = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = Lock()

    def acquire(self) -> bool:
        """尝试获取一个 token，返回 True 表示允许，False 表示限流。"""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * (self.rpm / 60.0),
            )
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


_buckets: dict[str, TokenBucket] = defaultdict(TokenBucket)


def check_rate_limit(tenant_id: str = "default") -> bool:
    """检查 tenant 是否被限流。

    Returns:
        True 表示允许，False 表示限流（调用方应返回 429）
    """
    return _buckets[tenant_id].acquire()


def get_rate_limit_stats() -> dict[str, dict]:
    """返回各 tenant 的限流状态。"""
    return {
        tid: {"rpm": b.rpm, "burst": b.capacity, "current_tokens": round(b.tokens, 2)}
        for tid, b in _buckets.items()
    }
