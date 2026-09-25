"""可观测性扩展测试：retrieval trace 新字段 + 越权/过期计数 + 成本字段 + OTel 持久化。

覆盖：
1. retrieval trace 新字段写入（priority_decision / conflict_decision / retrieval_hit_ids）
2. 越权召回计数（cross_tenant_recall_count，确定性判据恒为 0）
3. 过期知识召回计数（expired_knowledge_recall_count，确定性判据恒为 0）
4. 成本字段（model_used 对接 Model Router）
5. trace 持久化：InMemoryTraceRecorder + OTelTraceRecorder（no-op 降级）
6. 11 字段核心契约不被扩展字段破坏
"""

from __future__ import annotations

import pytest

from exhibition_agent.observability.trace import (
    TRACE_REQUIRED_FIELDS,
    InMemoryTraceRecorder,
    OTelTraceRecorder,
    TraceRecord,
)


def _make_trace(**overrides) -> TraceRecord:
    """构造测试用 TraceRecord（默认合法值，overrides 覆盖）。"""
    defaults = dict(
        request_id="req-ext-0001",
        tenant_id="t-001",
        skill="venue.schedule.query",
        latency_ms=12.3,
        readiness="READY",
        data_classification="INTERNAL",
        egress_decision="ALLOW",
        model="stub-private-qwen",
        cost=0.002,
        retrieval_hit_ids=["kb-001", "kb-002"],
        error_code=None,
    )
    defaults.update(overrides)
    return TraceRecord(**defaults)


# ---------------------------------------------------------------------------
# 1. retrieval trace 新字段写入
# ---------------------------------------------------------------------------
def test_trace_retrieval_extension_fields_default():
    """扩展字段默认值：priority_decision=None, conflict_decision=None, 计数=0, model_used=None。"""
    trace = _make_trace()
    assert trace.priority_decision is None
    assert trace.conflict_decision is None
    assert trace.cross_tenant_recall_count == 0
    assert trace.expired_knowledge_recall_count == 0
    assert trace.model_used is None


def test_trace_priority_decision_hard_soft():
    """priority_decision 写入 HARD/SOFT。"""
    t_hard = _make_trace(priority_decision="HARD")
    t_soft = _make_trace(priority_decision="SOFT")
    assert t_hard.priority_decision == "HARD"
    assert t_soft.priority_decision == "SOFT"


def test_trace_conflict_decision_left_trace():
    """conflict_decision 冲突判定留痕写入。"""
    trace = _make_trace(conflict_decision="RESOLVED_BY_PRIORITY")
    assert trace.conflict_decision == "RESOLVED_BY_PRIORITY"


def test_trace_retrieval_hit_ids_preserved():
    """retrieval_hit_ids 列表完整保留。"""
    ids = ["kb-001", "kb-002", "kb-003"]
    trace = _make_trace(retrieval_hit_ids=ids)
    assert trace.retrieval_hit_ids == ids


# ---------------------------------------------------------------------------
# 2. 越权召回计数（确定性判据：正常路径恒为 0）
# ---------------------------------------------------------------------------
def test_cross_tenant_recall_count_zero_on_normal_path():
    """正常路径：cross_tenant_recall_count == 0（确定性判据）。"""
    recorder = InMemoryTraceRecorder()
    recorder.record(_make_trace())
    assert recorder.cross_tenant_recall_count == 0


def test_cross_tenant_recall_count_accumulates_from_trace():
    """trace 自带 cross_tenant_recall_count 字段累加到 recorder。"""
    recorder = InMemoryTraceRecorder()
    recorder.record(_make_trace(cross_tenant_recall_count=2))
    recorder.record(_make_trace(cross_tenant_recall_count=1))
    assert recorder.cross_tenant_recall_count == 3


def test_cross_tenant_recall_count_explicit_record():
    """显式 record_cross_tenant_recall 调用累加。"""
    recorder = InMemoryTraceRecorder()
    recorder.record_cross_tenant_recall()
    recorder.record_cross_tenant_recall(3)
    assert recorder.cross_tenant_recall_count == 4


def test_cross_tenant_recall_count_violation_detected():
    """越权场景：cross_tenant_recall_count > 0（判据违反可观测）。"""
    recorder = InMemoryTraceRecorder()
    recorder.record(_make_trace(cross_tenant_recall_count=1))
    assert recorder.cross_tenant_recall_count >= 1


# ---------------------------------------------------------------------------
# 3. 过期知识召回计数（确定性判据：正常路径恒为 0）
# ---------------------------------------------------------------------------
def test_expired_knowledge_recall_count_zero_on_normal_path():
    """正常路径：expired_knowledge_recall_count == 0（确定性判据）。"""
    recorder = InMemoryTraceRecorder()
    recorder.record(_make_trace())
    assert recorder.expired_knowledge_recall_count == 0


def test_expired_knowledge_recall_count_accumulates_from_trace():
    """trace 自带 expired_knowledge_recall_count 字段累加到 recorder。"""
    recorder = InMemoryTraceRecorder()
    recorder.record(_make_trace(expired_knowledge_recall_count=1))
    recorder.record(_make_trace(expired_knowledge_recall_count=2))
    assert recorder.expired_knowledge_recall_count == 3


def test_expired_knowledge_recall_count_explicit_record():
    """显式 record_expired_knowledge_recall 调用累加。"""
    recorder = InMemoryTraceRecorder()
    recorder.record_expired_knowledge_recall()
    recorder.record_expired_knowledge_recall(5)
    assert recorder.expired_knowledge_recall_count == 6


# ---------------------------------------------------------------------------
# 4. 成本字段（model_used 对接 Model Router）
# ---------------------------------------------------------------------------
def test_trace_model_used_field():
    """model_used 字段写入 Model Router 实际路由结果。"""
    trace = _make_trace(model="default-private", model_used="qwen-72b-private")
    assert trace.model == "default-private"
    assert trace.model_used == "qwen-72b-private"


def test_trace_cost_field_preserved():
    """cost 字段完整保留（浮点精度）。"""
    trace = _make_trace(cost=0.00123)
    assert trace.cost == pytest.approx(0.00123)


def test_trace_model_and_model_used_coexist():
    """model（配置默认）与 model_used（实际路由）可并存且语义独立。"""
    trace = _make_trace(model="config-default", model_used="routed-actual")
    assert trace.model != trace.model_used


# ---------------------------------------------------------------------------
# 5. trace 持久化：InMemoryTraceRecorder
# ---------------------------------------------------------------------------
def test_inmemory_recorder_find_by_request_id():
    """InMemoryTraceRecorder.find_by_request_id 检索扩展字段完整。"""
    recorder = InMemoryTraceRecorder()
    trace = _make_trace(
        request_id="req-find-001",
        priority_decision="HARD",
        conflict_decision="NONE",
        model_used="qwen-72b",
        cross_tenant_recall_count=0,
        expired_knowledge_recall_count=0,
    )
    recorder.record(trace)
    found = recorder.find_by_request_id("req-find-001")
    assert found is not None
    assert found.priority_decision == "HARD"
    assert found.conflict_decision == "NONE"
    assert found.model_used == "qwen-72b"


def test_inmemory_recorder_reset_clears_counters():
    """reset() 清空 trace 队列 + 越权/过期计数器。"""
    recorder = InMemoryTraceRecorder()
    recorder.record(_make_trace(cross_tenant_recall_count=1, expired_knowledge_recall_count=2))
    assert recorder.cross_tenant_recall_count == 1
    assert recorder.expired_knowledge_recall_count == 2
    recorder.reset()
    assert recorder.cross_tenant_recall_count == 0
    assert recorder.expired_knowledge_recall_count == 0
    assert len(recorder.traces) == 0


# ---------------------------------------------------------------------------
# 5b. trace 持久化：OTelTraceRecorder（no-op 降级，不强制依赖 otel）
# ---------------------------------------------------------------------------
def test_otel_recorder_noop_mode_does_not_crash():
    """OTel SDK 缺失时 OTelTraceRecorder.record 走 no-op 不崩。"""
    recorder = OTelTraceRecorder()
    trace = _make_trace(priority_decision="HARD", model_used="qwen-72b")
    recorder.record(trace)  # 不应抛异常
    assert recorder.recorded_count == 1


def test_otel_recorder_records_multiple():
    """OTelTraceRecorder 多次记录计数正确。"""
    recorder = OTelTraceRecorder()
    for i in range(5):
        recorder.record(_make_trace(request_id=f"req-otel-{i}"))
    assert recorder.recorded_count == 5


def test_otel_recorder_trace_to_attrs_complete():
    """_trace_to_attrs 包含核心 + 扩展字段（None 值跳过）。"""
    trace = _make_trace(
        priority_decision="HARD",
        conflict_decision="RESOLVED",
        model_used="qwen-72b",
        error_code="SOME_ERROR",
    )
    attrs = OTelTraceRecorder._trace_to_attrs(trace)
    # 核心字段
    assert attrs["trace.request_id"] == trace.request_id
    assert attrs["trace.skill"] == trace.skill
    assert attrs["trace.cost"] == trace.cost
    assert attrs["trace.retrieval_hit_ids"] == "kb-001,kb-002"
    # 扩展字段
    assert attrs["trace.priority_decision"] == "HARD"
    assert attrs["trace.conflict_decision"] == "RESOLVED"
    assert attrs["trace.model_used"] == "qwen-72b"
    assert attrs["trace.error_code"] == "SOME_ERROR"
    assert attrs["trace.cross_tenant_recall_count"] == 0
    assert attrs["trace.expired_knowledge_recall_count"] == 0


def test_otel_recorder_trace_to_attrs_skips_none():
    """_trace_to_attrs 跳过 None 值扩展字段。"""
    trace = _make_trace()  # 默认 priority_decision=None, conflict_decision=None, model_used=None
    attrs = OTelTraceRecorder._trace_to_attrs(trace)
    assert "trace.priority_decision" not in attrs
    assert "trace.conflict_decision" not in attrs
    assert "trace.model_used" not in attrs
    assert "trace.error_code" not in attrs


def test_otel_recorder_satisfies_protocol():
    """OTelTraceRecorder 满足 TraceRecorder 协议（duck typing）。"""
    recorder: OTelTraceRecorder = OTelTraceRecorder()
    assert hasattr(recorder, "record")
    recorder.record(_make_trace())  # 协议方法可调用


# ---------------------------------------------------------------------------
# 6. 11 字段核心契约不被扩展字段破坏
# ---------------------------------------------------------------------------
def test_trace_required_fields_still_11():
    """扩展后核心契约字段数仍为 11（扩展字段可选，不计入核心契约）。"""
    assert len(TRACE_REQUIRED_FIELDS) == 11


def test_trace_core_fields_still_present():
    """扩展后核心 11 字段仍全部存在且可访问。"""
    trace = _make_trace()
    for field in TRACE_REQUIRED_FIELDS:
        assert hasattr(trace, field), f"核心字段缺失：{field}"


def test_trace_construct_without_extension_fields():
    """仅用核心 11 字段构造 TraceRecord 仍成功（扩展字段默认值）。"""
    trace = TraceRecord(
        request_id="req-min-001",
        tenant_id="t-001",
        skill="venue.schedule.query",
        latency_ms=1.0,
        readiness="READY",
        data_classification="INTERNAL",
        egress_decision="ALLOW",
        model="stub",
        cost=0.0,
        retrieval_hit_ids=[],
        error_code=None,
    )
    assert trace.priority_decision is None
    assert trace.cross_tenant_recall_count == 0
    assert trace.expired_knowledge_recall_count == 0
    assert trace.model_used is None
