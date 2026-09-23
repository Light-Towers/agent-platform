"""C4 评测与可观测契约：trace 最小字段（11 个，缺一不可）+ 检索/成本/越权扩展。

字段（契约 §C4，11 个核心字段缺一不可）：
    request_id · tenant_id · skill · latency_ms · readiness
    data_classification · egress_decision · model · cost
    retrieval_hit_ids[] · error_code（如有）

扩展字段（可选，默认零值/None，不破坏 11 字段契约）：
    priority_decision · conflict_decision
    cross_tenant_recall_count · expired_knowledge_recall_count
    model_used（Model Router 实际路由结果，与 model 区分）

确定性验收判据：
    - trace 缺失 request_id 数 = 0
    - cross_tenant_recall_count == 0（无越权召回）
    - expired_knowledge_recall_count == 0（无过期知识召回）
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Protocol

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
    """单次调用的 trace 记录（C4 最小字段集 + 检索/成本/越权扩展）。

    前 10 个字段必填；error_code 可选（None 表示无错误）。
    扩展字段全部可选（默认零值/None），不影响 11 字段契约。
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
    # 检索扩展：优先级判定（HARD/SOFT）+ 冲突判定留痕
    priority_decision: str | None = None
    conflict_decision: str | None = None
    # 越权/过期召回计数（确定性判据：恒为 0）
    cross_tenant_recall_count: int = 0
    expired_knowledge_recall_count: int = 0
    # 成本可观测：Model Router 实际路由到的模型（与 model 区分：model 是配置默认）
    model_used: str | None = None


class TraceRecorder(Protocol):
    """trace 记录器协议。"""

    def record(self, trace: TraceRecord) -> None: ...


class InMemoryTraceRecorder:
    """内存 trace 收集器（测试断言用）。

    有界队列（审核建议 5）：默认 maxlen=1000，防长期运行进程无界增长；
    超出后丢弃最旧记录（find_by_request_id 对近期 request_id 仍可用）。

    内置越权召回 / 过期知识召回计数器（C4 确定性判据：正常路径恒为 0）。
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self.traces: deque[TraceRecord] = deque(maxlen=maxlen)
        self._cross_tenant_recall_count: int = 0
        self._expired_knowledge_recall_count: int = 0

    def record(self, trace: TraceRecord) -> None:
        self.traces.append(trace)
        # 累计越权/过期召回计数（trace 自带字段 + 显式 record 方法双通道）
        self._cross_tenant_recall_count += trace.cross_tenant_recall_count
        self._expired_knowledge_recall_count += trace.expired_knowledge_recall_count
        logger.info(
            "trace recorded request_id=%s skill=%s readiness=%s latency_ms=%.1f "
            "error_code=%s cross_tenant_recall=%d expired_knowledge_recall=%d",
            trace.request_id,
            trace.skill,
            trace.readiness,
            trace.latency_ms,
            trace.error_code,
            trace.cross_tenant_recall_count,
            trace.expired_knowledge_recall_count,
        )

    def record_cross_tenant_recall(self, count: int = 1) -> None:
        """显式记录越权召回次数（检索链路发现跨租户命中时调用）。"""
        self._cross_tenant_recall_count += count

    def record_expired_knowledge_recall(self, count: int = 1) -> None:
        """显式记录过期知识召回次数（检索链路发现命中已过期知识时调用）。"""
        self._expired_knowledge_recall_count += count

    @property
    def cross_tenant_recall_count(self) -> int:
        return self._cross_tenant_recall_count

    @property
    def expired_knowledge_recall_count(self) -> int:
        return self._expired_knowledge_recall_count

    def find_by_request_id(self, request_id: str) -> TraceRecord | None:
        for t in self.traces:
            if t.request_id == request_id:
                return t
        return None

    def reset(self) -> None:
        """清空 trace 队列 + 计数器（测试隔离用）。"""
        self.traces.clear()
        self._cross_tenant_recall_count = 0
        self._expired_knowledge_recall_count = 0


class OTelTraceRecorder:
    """OTel trace 记录器：将 TraceRecord 写入 OTel span（可选依赖，缺 SDK 走 no-op）。

    复用 exhibition_agent.observability.otel.span（封装 agent_core.tracing），
    OTel SDK 缺失或未 init 时 span 走 no-op 降级，绝不抛异常。

    用法：
        recorder = OTelTraceRecorder()
        recorder.record(trace)  # 在 OTel span 上设置 trace 全字段为属性
    """

    def __init__(self, span_name: str = "exhibition_agent.trace") -> None:
        self._span_name = span_name
        self._recorded: int = 0

    def record(self, trace: TraceRecord) -> None:
        """将 trace 记录到 OTel span（no-op 模式下不崩）。"""
        from exhibition_agent.observability.otel import span

        attrs = self._trace_to_attrs(trace)
        with span(self._span_name, **attrs) as s:
            # no-op span 也支持 set_attribute，这里再设一遍以防 attrs 被过滤
            for k, v in attrs.items():
                try:
                    s.set_attribute(k, v)
                except Exception:  # noqa: BLE001 - pragma: no cover - no-op span 不应抛
                    pass
        self._recorded += 1

    @staticmethod
    def _trace_to_attrs(trace: TraceRecord) -> dict[str, Any]:
        """将 TraceRecord 转为 OTel span 属性 dict（None 值跳过）。"""
        attrs: dict[str, Any] = {
            "trace.request_id": trace.request_id,
            "trace.tenant_id": trace.tenant_id,
            "trace.skill": trace.skill,
            "trace.latency_ms": trace.latency_ms,
            "trace.readiness": trace.readiness,
            "trace.data_classification": trace.data_classification,
            "trace.egress_decision": trace.egress_decision,
            "trace.model": trace.model,
            "trace.cost": trace.cost,
            "trace.retrieval_hit_ids": ",".join(trace.retrieval_hit_ids),
            "trace.cross_tenant_recall_count": trace.cross_tenant_recall_count,
            "trace.expired_knowledge_recall_count": trace.expired_knowledge_recall_count,
        }
        if trace.error_code is not None:
            attrs["trace.error_code"] = trace.error_code
        if trace.priority_decision is not None:
            attrs["trace.priority_decision"] = trace.priority_decision
        if trace.conflict_decision is not None:
            attrs["trace.conflict_decision"] = trace.conflict_decision
        if trace.model_used is not None:
            attrs["trace.model_used"] = trace.model_used
        return attrs

    @property
    def recorded_count(self) -> int:
        """已记录的 trace 数（测试断言用）。"""
        return self._recorded


def now_ms() -> float:
    """当前时间戳（毫秒），供 latency 计算。"""
    return time.monotonic() * 1000.0
