"""可观测性测试：OTel span + W3C traceparent 传播 + metrics C4 确定性判据。

OTel SDK 未安装时全部走 no-op 降级路径（零开销、绝不抛异常）——本测试集验证：
1. span 上下文管理器在 no-op 模式下可用不崩
2. traceparent inject/extract 在 no-op 模式下 no-op 不崩
3. init_observability 幂等、no-op 模式不崩
4. MetricsRegistry 计数器 + 直方图 + 快照 + 重置
5. C4 确定性判据：正常路径 scope_denied_count == 0
6. C4 确定性判据：越权场景 scope_denied_count == 1
7. 全链路 metrics 记录：latency / readiness / error_code 经 supervisor 贯穿
8. warehouse_client.invoke 注入 traceparent 不崩（no-op 模式）
"""

from __future__ import annotations

import pytest

from exhibition_agent.config import Settings
from exhibition_agent.graph.supervisor import run_supervisor
from exhibition_agent.observability.metrics import MetricsRegistry
from exhibition_agent.observability.otel import (
    extract_traceparent,
    get_current_traceparent,
    init_observability,
    inject_traceparent,
    span,
    use_context,
)
from exhibition_agent.observability.trace import InMemoryTraceRecorder
from exhibition_agent.testing_helpers import ctx, ctx_header


# ---------------------------------------------------------------------------
# 1. span 上下文管理器（no-op 模式）
# ---------------------------------------------------------------------------
def test_span_noop_mode_does_not_crash():
    """no-op 模式下 span 可用不崩（OTel SDK 缺失时走 _NoOpSpanContextManager）。"""
    with span("test.span", request_id="req-001") as s:
        s.set_attribute("key", "value")
        s.set_attributes({"a": 1, "b": 2})
    assert s is not None


def test_span_nested_noop():
    """嵌套 span 在 no-op 模式下不崩。"""
    with span("test.outer") as outer:
        with span("test.inner") as inner:
            pass
    assert outer is not None
    assert inner is not None


def test_span_exception_propagation():
    """span 内异常不吞、正常抛出。"""
    with pytest.raises(ValueError, match="boom"):
        with span("test.exc"):
            raise ValueError("boom")


# ---------------------------------------------------------------------------
# 2. traceparent inject/extract（no-op 模式）
# ---------------------------------------------------------------------------
def test_inject_traceparent_noop_returns_headers():
    """no-op 模式下 inject_traceparent 原样返回 headers（不崩）。"""
    headers = {"X-Custom": "val"}
    result = inject_traceparent(headers)
    assert result is headers or result == headers


def test_extract_traceparent_noop_returns_none_or_context():
    """no-op 模式下 extract_traceparent 返回 None 或空 context（不崩）。"""
    result = extract_traceparent({"traceparent": "00-aaa-bbb-01"})
    assert result is None


def test_use_context_none_returns_nullcontext():
    """use_context(None) 返回 nullcontext（不崩）。"""
    cm = use_context(None)
    with cm:
        pass


def test_get_current_traceparent_noop_returns_none():
    """no-op 模式下 get_current_traceparent 返回 None（不崩）。"""
    result = get_current_traceparent()
    assert result is None


# ---------------------------------------------------------------------------
# 3. init_observability 幂等
# ---------------------------------------------------------------------------
def test_init_observability_idempotent():
    """init_observability 可重复调用不崩（agent_core.tracing.init_tracing 幂等）。"""
    s = Settings(otel_enabled=False, otel_endpoint=None)
    tracer1 = init_observability(s)
    tracer2 = init_observability(s)
    assert tracer1 is tracer2


def test_init_observability_enabled_but_no_sdk():
    """enabled=True 但 SDK 缺失 → no-op 降级不崩。"""
    s = Settings(otel_enabled=True, otel_endpoint="http://localhost:4317")
    tracer = init_observability(s)
    assert tracer is not None


# ---------------------------------------------------------------------------
# 4. MetricsRegistry 单元
# ---------------------------------------------------------------------------
def test_metrics_registry_basic():
    reg = MetricsRegistry()
    reg.record_latency("venue.schedule.query", 12.5)
    reg.record_latency("venue.schedule.query", 8.3)
    reg.record_error_code("METRIC_NOT_VERIFIED")
    reg.record_readiness("READY")
    reg.record_readiness("NOT_CONNECTED")
    reg.record_scope_denied()
    reg.record_readiness_missing()
    reg.record_knowledge_not_published()

    assert reg.latency_samples["venue.schedule.query"] == [12.5, 8.3]
    assert reg.error_code_counts == {"METRIC_NOT_VERIFIED": 1}
    assert reg.readiness_counts == {"READY": 1, "NOT_CONNECTED": 1}
    assert reg.scope_denied_count == 1
    assert reg.readiness_missing_count == 1
    assert reg.knowledge_not_published_count == 1


def test_metrics_registry_snapshot():
    reg = MetricsRegistry()
    reg.record_latency("s1", 1.0)
    reg.record_error_code("INTERNAL")
    snap = reg.snapshot()
    assert snap["latency_samples"] == {"s1": [1.0]}
    assert snap["error_code_counts"] == {"INTERNAL": 1}
    assert snap["scope_denied_count"] == 0


def test_metrics_registry_reset():
    reg = MetricsRegistry()
    reg.record_scope_denied()
    reg.record_latency("s1", 1.0)
    reg.reset()
    assert reg.scope_denied_count == 0
    assert reg.latency_samples == {}


def test_metrics_registry_thread_safe():
    """并发 record 不崩（锁保护）。"""
    import threading

    reg = MetricsRegistry()
    threads = []
    for _ in range(10):
        t = threading.Thread(target=lambda: reg.record_scope_denied())
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert reg.scope_denied_count == 10


# ---------------------------------------------------------------------------
# 5. C4 确定性判据：正常路径 scope_denied_count == 0
# ---------------------------------------------------------------------------
async def test_c4_scope_denied_zero_on_normal_path(warehouse_client):
    """正常 200 路径：scope_denied_count == 0（C4 确定性判据）。"""
    reg = MetricsRegistry()
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆排期",
        "params": {"venue_id": "vn-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "metrics_registry": reg,
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    })

    assert state["skill_result"] is not None
    assert reg.scope_denied_count == 0, (
        f"C4 判据违反：正常路径 scope_denied_count 应为 0，实际 {reg.scope_denied_count}"
    )
    assert reg.readiness_counts.get("READY", 0) == 1
    assert "venue.schedule.query" in reg.latency_samples
    assert len(reg.latency_samples["venue.schedule.query"]) == 1


# ---------------------------------------------------------------------------
# 6. C4 确定性判据：越权场景 scope_denied_count >= 1
# ---------------------------------------------------------------------------
async def test_c4_scope_denied_on_denied_scenario(warehouse_client):
    """SCOPE_DENIED 场景：scope_denied_count >= 1。"""
    reg = MetricsRegistry()
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆排期",
        "params": {"venue_id": "vn-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "metrics_registry": reg,
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "scope_denied"},
    })

    assert state["skill_result"] is not None
    assert state["skill_result"].error_code == "SCOPE_DENIED"
    assert reg.scope_denied_count == 1, (
        f"C4 判据：SCOPE_DENIED 场景 scope_denied_count 应为 1，实际 {reg.scope_denied_count}"
    )


# ---------------------------------------------------------------------------
# 7. 全链路 metrics：error_code 经 supervisor 贯穿
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scenario,expected_code", [
    ("metric_not_verified", "METRIC_NOT_VERIFIED"),
    ("metric_blocked", "METRIC_BLOCKED"),
    ("data_not_connected", "DATA_NOT_CONNECTED"),
])
async def test_metrics_error_code_through_supervisor(
    warehouse_client, scenario, expected_code
):
    """指标未就绪场景：error_code 计数器经 supervisor 贯穿到 metrics。"""
    reg = MetricsRegistry()
    context = ctx()
    await run_supervisor({
        "query": "查询指标",
        "params": {"metric": "sales_rate"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "metrics_registry": reg,
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": scenario},
    })

    assert reg.error_code_counts.get(expected_code, 0) == 1
    assert reg.readiness_counts.get("NOT_CONNECTED", 0) == 1


async def test_metrics_knowledge_not_published(warehouse_client):
    """KNOWLEDGE_NOT_PUBLISHED 场景：knowledge_not_published_count == 1。"""
    reg = MetricsRegistry()
    context = ctx()
    await run_supervisor({
        "query": "查询知识",
        "params": {},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "metrics_registry": reg,
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "knowledge_not_published"},
    })

    assert reg.knowledge_not_published_count == 1
    assert reg.error_code_counts.get("KNOWLEDGE_NOT_PUBLISHED", 0) == 1


# ---------------------------------------------------------------------------
# 8. warehouse_client.invoke 注入 traceparent 不崩
# ---------------------------------------------------------------------------
async def test_warehouse_client_invoke_injects_traceparent(warehouse_client):
    """WarehouseClient.get_rest 注入 traceparent 到 headers（no-op 模式不崩）。"""
    context = ctx()
    result = await warehouse_client.get_rest(
        "/api/venue-schedule",
        params={"venue_id": "vn-001"},
        execution_context_header=ctx_header(context),
        request_id=context.request_id,
        context_mode="jwt",
        extra_headers={"X-Mock-Scenario": "normal_200"},
    )
    assert result is not None
    assert result["data_readiness"]["level"] == "complete"


async def test_warehouse_client_invoke_with_traceparent_no_crash(warehouse_client):
    """traceparent 注入/提取全链路不崩（no-op 模式下 no-op 但不报错）。"""
    headers: dict[str, str] = {"X-Custom": "val"}
    inject_traceparent(headers)
    extracted = extract_traceparent(headers)
    with use_context(extracted):
        with span("test.warehouse_call", request_id="req-001"):
            pass
