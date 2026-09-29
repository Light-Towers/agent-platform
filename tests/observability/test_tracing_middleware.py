# -*- coding: utf-8 -*-
"""S2/S3 真 SDK 观测钉用例（方案 §3.3 CI 真路径补盲，终结 R3/R6/R10/R11 复发面）。

运行前提：真实 opentelemetry SDK —— ``uv run --extra otel pytest tests/observability -q``
（Makefile ``test`` 目标已含本 session）；默认 root session 不装 SDK 时整模块
``importorskip`` 自动 skip（守卫设计意图，非失败，opt-in 铁律不破）。

钉住的行为：
1. **旁路覆盖（R10）**：TracingMiddleware 为每个 HTTP 请求产出 span——含 429 拒绝、
   500 异常路径（handler 手写 span 时代这些路径失明）；
2. **traceparent 父子一致（R6）**：入站头 trace-id/span-id 段 == span 的
   trace_id/parent.span_id（跨服务串联的机器可验证据）；
3. **业务属性经 record_request_attributes 落中间件请求 span**（R8 手写 span 退役后的正规面）;
4. **三态可查（R5/R11）**：注入 exporter init 后 status=ACTIVE 且 ``is_tracing_enabled()==True``。

注：本模块 module 级 init 一次（kernel 幂等 + 全局 provider 一次性），span 按
``http.target`` 唯一路径过滤断言，避免跨用例串扰。
"""

from __future__ import annotations

import pytest

# 真 SDK 前提：默认 CI/本地无 SDK 环境整模块 skip（设计意图）
pytest.importorskip("opentelemetry.sdk", reason="需真 opentelemetry-sdk（--extra otel session）")

from agent_core import tracing as kernel  # noqa: E402
from agent_core.guardrails.app_factory import build_api_app  # noqa: E402
from agent_core.tracing import record_request_attributes  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind  # noqa: E402

_TRACE_ID = "0123456789abcdef0123456789abcdef"
_PARENT_SPAN_ID = "0123456789abcdef"


@pytest.fixture(scope="module")
def span_exporter():
    """module 级真 init：注入 InMemorySpanExporter（SimpleSpanProcessor 同步导出）。"""
    kernel._reset_for_tests()
    exporter = InMemorySpanExporter()
    tracer = kernel.init_tracing(service_name="obs-tests", enabled=True, exporter=exporter)
    assert tracer is not None
    assert kernel.is_tracing_enabled() is True
    assert kernel.get_tracing_status()["status"] == "ACTIVE"
    yield exporter
    kernel._reset_for_tests()


@pytest.fixture(scope="module")
def client(span_exporter):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    app = build_api_app(enable_tracing=True)

    @app.get("/mw-ok")
    async def mw_ok():
        record_request_attributes({"biz.marker": "ok-route"})
        return {"ok": True}

    @app.get("/mw-reject")
    async def mw_reject():
        record_request_attributes({"biz.marker": "reject-route"})
        raise HTTPException(status_code=429, detail="RATE_LIMITED")

    @app.get("/mw-boom")
    async def mw_boom():
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def _spans_for(exporter: InMemorySpanExporter, target: str) -> list:
    return [s for s in exporter.get_finished_spans() if s.attributes.get("http.target") == target]


def test_middleware_span_on_happy_path(client, span_exporter):
    """200 正常路径：产出 SERVER span 且带 status_code/method 属性。"""
    resp = client.get("/mw-ok")
    assert resp.status_code == 200
    spans = _spans_for(span_exporter, "/mw-ok")
    assert len(spans) == 1
    span = spans[0]
    assert span.kind == SpanKind.SERVER
    assert span.attributes.get("http.method") == "GET"
    assert span.attributes.get("http.status_code") == 200
    # R8 退役后的正规面：业务属性经 record_request_attributes 落中间件请求 span
    assert span.attributes.get("biz.marker") == "ok-route"


def test_middleware_span_on_bypass_429(client, span_exporter):
    """R10 终结：429 旁路（handler 早段 raise）同样产出 span——手写 span 时代此路失明。"""
    resp = client.get("/mw-reject")
    assert resp.status_code == 429
    spans = _spans_for(span_exporter, "/mw-reject")
    assert len(spans) == 1
    assert spans[0].attributes.get("http.status_code") == 429
    assert spans[0].attributes.get("biz.marker") == "reject-route"


def test_middleware_span_on_unhandled_500(client, span_exporter):
    """R10：未捕获异常路径落 span 且置 ERROR 状态（断连/异常不再静默）。

    注：500 响应由外层 ServerErrorMiddleware 合成（不经本中间件的 send 包装），
    故不断言 http.status_code 属性，断言 ERROR 状态即可。
    """
    resp = client.get("/mw-boom")
    assert resp.status_code == 500
    spans = _spans_for(span_exporter, "/mw-boom")
    assert len(spans) == 1
    assert spans[0].status.status_code.name == "ERROR"


def test_traceparent_header_becomes_span_parent(client, span_exporter):
    """R6 终结钉：入站 traceparent 的 trace-id/span-id 段 == span trace_id/parent_span_id。

    按固定 trace_id 过滤（非计数断言），``--lf`` 复跑单用例也不受其他用例影响。
    """
    resp = client.get(
        "/mw-ok",
        headers={"traceparent": f"00-{_TRACE_ID}-{_PARENT_SPAN_ID}-01"},
    )
    assert resp.status_code == 200
    spans = [
        s
        for s in span_exporter.get_finished_spans()
        if s.attributes.get("http.target") == "/mw-ok"
        and s.get_span_context().trace_id == int(_TRACE_ID, 16)
    ]
    assert len(spans) == 1
    span = spans[0]
    assert span.parent is not None
    assert span.parent.span_id == int(_PARENT_SPAN_ID, 16)


def test_kernel_tri_state_active(span_exporter):
    """R5/R11：注入 exporter 的真 init 三态落 ACTIVE（/health 直读此状态机）。"""
    status = kernel.get_tracing_status()
    assert status["status"] == "ACTIVE"
    assert status["reason"] == ""
