"""C4 评测与可观测契约：trace 最小字段（11 个，缺一不可）。

字段（契约 §C4）：
    request_id · tenant_id · skill · latency_ms · readiness
    data_classification · egress_decision · model · cost
    retrieval_hit_ids[] · error_code（如有）

确定性验收判据：trace 缺失 request_id 数 = 0。
"""

from __future__ import annotations

import time
from typing import Protocol

from agent_core.logging import get_logger
from pydantic import BaseModel, Field

logger = get_logger(__name__)

TRACE_REQUIRED_FIELDS: tuple[str, ...] = (
    "request_id",
    "tenant_id",
    "skill",
    "latency_ms",
    "readiness",
    "data_classification",
    "egress_decision",
    "model",
    "cost",
    "retrieval_hit_ids",
    "error_code",
)


class TraceRecord(BaseModel):
    """单次调用的 trace 记录（C4 最小字段集）。

    前 10 个字段必填；error_code 可选（None 表示无错误）。
    """

    request_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    skill: str
    latency_ms: float
    readiness: str
    data_classification: str
    egress_decision: str
    model: str
    cost: float
    retrieval_hit_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None


class TraceRecorder(Protocol):
    """trace 记录器协议。"""

    def record(self, trace: TraceRecord) -> None: ...


class InMemoryTraceRecorder:
    """内存 trace 收集器（测试断言用）。"""

    def __init__(self) -> None:
        self.traces: list[TraceRecord] = []

    def record(self, trace: TraceRecord) -> None:
        self.traces.append(trace)
        logger.info(
            "trace recorded request_id=%s skill=%s readiness=%s latency_ms=%.1f error_code=%s",
            trace.request_id,
            trace.skill,
            trace.readiness,
            trace.latency_ms,
            trace.error_code,
        )

    def find_by_request_id(self, request_id: str) -> TraceRecord | None:
        for t in self.traces:
            if t.request_id == request_id:
                return t
        return None


def now_ms() -> float:
    """当前时间戳（毫秒），供 latency 计算。"""
    return time.monotonic() * 1000.0
