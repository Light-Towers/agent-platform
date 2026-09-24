"""轻量 metrics 注册表（不引入 prometheus/otel meter 重依赖）。

计数器：
    - error_code 计数器（按错误码分桶）
    - scope_denied 计数器（C4 确定性判据：正常路径恒 = 0）
    - readiness 计数器（按 readiness 值分桶）
    - readiness_missing 计数器（缺 readiness 判 fail 次数）
    - knowledge_not_published 计数器

直方图：
    - latency 直方图（按 skill 分桶，存原始样本供测试断言）
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class MetricsRegistry:
    """轻量线程安全 metrics 注册表（进程内，测试断言用）。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._error_code_counts: dict[str, int] = defaultdict(int)
        self._scope_denied_count: int = 0
        self._readiness_counts: dict[str, int] = defaultdict(int)
        self._readiness_missing_count: int = 0
        self._knowledge_not_published_count: int = 0
        self._latency_samples: dict[str, list[float]] = defaultdict(list)

    def record_error_code(self, code: str) -> None:
        with self._lock:
            self._error_code_counts[code] += 1

    def record_scope_denied(self) -> None:
        with self._lock:
            self._scope_denied_count += 1

    def record_readiness(self, value: str) -> None:
        with self._lock:
            self._readiness_counts[value] += 1

    def record_readiness_missing(self) -> None:
        with self._lock:
            self._readiness_missing_count += 1

    def record_knowledge_not_published(self) -> None:
        with self._lock:
            self._knowledge_not_published_count += 1

    def record_latency(self, skill: str, latency_ms: float) -> None:
        with self._lock:
            self._latency_samples[skill].append(latency_ms)

    @property
    def scope_denied_count(self) -> int:
        with self._lock:
            return self._scope_denied_count

    @property
    def readiness_missing_count(self) -> int:
        with self._lock:
            return self._readiness_missing_count

    @property
    def knowledge_not_published_count(self) -> int:
        with self._lock:
            return self._knowledge_not_published_count

    @property
    def error_code_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._error_code_counts)

    @property
    def readiness_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._readiness_counts)

    @property
    def latency_samples(self) -> dict[str, list[float]]:
        with self._lock:
            return dict(self._latency_samples)

    def snapshot(self) -> dict[str, Any]:
        """全量快照（测试断言用）。"""
        with self._lock:
            return {
                "error_code_counts": dict(self._error_code_counts),
                "scope_denied_count": self._scope_denied_count,
                "readiness_counts": dict(self._readiness_counts),
                "readiness_missing_count": self._readiness_missing_count,
                "knowledge_not_published_count": self._knowledge_not_published_count,
                "latency_samples": dict(self._latency_samples),
            }

    def reset(self) -> None:
        """清空全部计数（测试隔离用）。"""
        with self._lock:
            self._error_code_counts.clear()
            self._scope_denied_count = 0
            self._readiness_counts.clear()
            self._readiness_missing_count = 0
            self._knowledge_not_published_count = 0
            self._latency_samples.clear()


_default_registry = MetricsRegistry()


def get_default_registry() -> MetricsRegistry:
    """进程级默认 metrics 注册表。"""
    return _default_registry
