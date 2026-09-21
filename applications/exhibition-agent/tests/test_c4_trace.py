"""C4 trace 测试（11 字段缺一不可）。"""

from __future__ import annotations

import pytest

from exhibition_agent.contract.envelope import DataClassification, EgressDecision, Readiness
from exhibition_agent.observability.trace import TRACE_REQUIRED_FIELDS, TraceRecord


def test_trace_required_fields_count():
    """契约 C4：11 个字段缺一不可。"""
    assert len(TRACE_REQUIRED_FIELDS) == 11


def test_trace_all_fields_present():
    trace = TraceRecord(
        request_id="req-0001",
        tenant_id="t-001",
        skill="venue.schedule.query",
        latency_ms=12.3,
        readiness=Readiness.READY.value,
        data_classification=DataClassification.INTERNAL.value,
        egress_decision=EgressDecision.ALLOW.value,
        model="stub-private-qwen",
        cost=0.0,
        retrieval_hit_ids=["kb-001"],
        error_code=None,
    )
    for field in TRACE_REQUIRED_FIELDS:
        assert hasattr(trace, field), f"trace 缺字段：{field}"


def test_trace_request_id_mandatory():
    """trace 缺失 request_id 数 = 0（确定性判据）。"""
    with pytest.raises(Exception):
        TraceRecord(
            request_id="",
            tenant_id="t-001",
            skill="venue.schedule.query",
            latency_ms=1.0,
            readiness="READY",
            data_classification="INTERNAL",
            egress_decision="ALLOW",
            model="stub",
            cost=0.0,
        )
