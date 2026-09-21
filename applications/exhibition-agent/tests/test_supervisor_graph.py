"""Supervisor 图测试：提问 → 选 skill → 调契约 → 回答带 citation + readiness。"""

from __future__ import annotations

from exhibition_agent.contract.envelope import Readiness
from exhibition_agent.graph.supervisor import run_supervisor
from exhibition_agent.observability.trace import InMemoryTraceRecorder
from exhibition_agent.testing_helpers import ctx, ctx_header


async def test_supervisor_normal_flow(warehouse_client):
    context = ctx()
    recorder = InMemoryTraceRecorder()
    state = await run_supervisor({
        "query": "查询 SIAL 广州 2026 场馆档期",
        "params": {"exhibition_id": "ex-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": recorder,
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    })

    result = state["skill_result"]
    assert result is not None
    assert result.readiness == Readiness.READY
    assert len(result.citations) >= 1
    assert "保利世贸博览馆" in state["answer"]

    trace = recorder.find_by_request_id(context.request_id)
    assert trace is not None
    assert trace.tenant_id == context.tenant_id
    assert trace.skill == "venue.schedule.query"
    assert trace.readiness == "READY"


async def test_supervisor_no_sql_generated(warehouse_client):
    """只读链路：全程未生成任何 SQL（sql_statements 为空）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "查询档期",
        "params": {"exhibition_id": "ex-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    })
    assert state["sql_statements"] == []
