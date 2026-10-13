# -*- coding: utf-8 -*-
"""D-LF-1 钉用例：复用宿主全局 TracerProvider 时，本平台必须确有 OTLP 出口。

运行前提：真实 opentelemetry SDK —— ``uv run --extra otel pytest tests/observability -q``；
默认 root session 无 SDK 时整模块 importorskip 自动 skip（与同目录约定一致）。

钉住的现网缺陷（2026-10-13，方案 docs/plans/plan-langfuse-wiring-2026-10-13.md §7）：
Langfuse 客户端构造会把全局 TracerProvider 换成它自己那份（只有 LangfuseSpanProcessor、不导 OTLP）。
kernel 的"复用已存在 provider"分支当时假设**宿主自带 exporter**，于是什么都不挂 ⇒
Jaeger 面整体静默，而 ``/health`` 仍报 ``otel_status=ACTIVE``（一盏说活着、一盏其实瞎）。
另一半缺陷更隐蔽：注入 exporter 的分支在复用判定**之前**就挂到了随后被丢弃的自建 provider 上（孤儿）。

三条合起来把"顺序决定生死"改成"顺序无关"：宿主有 OTLP ⇒ 不重复挂；宿主没有 ⇒ 补挂；
注入的 exporter ⇒ 挂到真正生效的那个 provider，且 span 真能到达它。
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk", reason="需真 opentelemetry-sdk（--extra otel session）")

from agent_core import tracing as kernel  # noqa: E402
from opentelemetry import trace as otel_trace_api  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

_OTLP_ENDPOINT = "http://127.0.0.1:59999"


@pytest.fixture(autouse=True)
def _isolate():
    kernel._reset_for_tests()
    yield
    kernel._reset_for_tests()


def _processors(provider):
    return list(getattr(provider._active_span_processor, "_span_processors", []))


def _otlp_exporter_count(provider) -> int:
    cls = kernel._OTLP_EXPORTER_CLS
    n = 0
    for sp in _processors(provider):
        # 属性名随 processor 类型而异：SimpleSpanProcessor.span_exporter / BatchSpanProcessor.exporter
        exp = (getattr(sp, "span_exporter", None) or getattr(sp, "exporter", None)
               or getattr(sp, "_exporter", None))
        if cls is not None and isinstance(exp, cls):
            n += 1
    return n


def _foreign_provider_without_otlp() -> TracerProvider:
    """造一个"Langfuse 式"宿主 provider：真 SDK provider，但出口不是 OTLP。"""
    p = TracerProvider()
    p.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    otel_trace_api.set_tracer_provider(p)
    return p


def test_foreign_provider_without_otlp_gets_our_exporter():
    """复用分支：宿主 provider 没有 OTLP 出口 ⇒ 必须补挂，且状态才允许是 ACTIVE。"""
    foreign = _foreign_provider_without_otlp()
    assert _otlp_exporter_count(foreign) == 0

    kernel.init_tracing(enabled=True, service_name="d-lf-1", otel_endpoint=_OTLP_ENDPOINT)

    assert otel_trace_api.get_tracer_provider() is foreign, "不该覆盖宿主全局 provider"
    assert _otlp_exporter_count(foreign) == 1, "复用路径没挂 OTLP 出口 ⇒ Jaeger 会静默瞎掉"
    st = kernel.get_tracing_status()
    assert st["status"] == "ACTIVE", st


def test_foreign_provider_with_otlp_is_not_duplicated():
    """宿主已有 OTLP 出口 ⇒ 不重复挂（同一 span 落两遍也是缺陷）。"""
    foreign = TracerProvider()
    foreign.add_span_processor(
        SimpleSpanProcessor(kernel._OTLP_EXPORTER_CLS(endpoint=_OTLP_ENDPOINT)))
    otel_trace_api.set_tracer_provider(foreign)

    kernel.init_tracing(enabled=True, service_name="d-lf-1-dup", otel_endpoint=_OTLP_ENDPOINT)

    assert _otlp_exporter_count(foreign) == 1


def test_injected_exporter_delivers_through_host_provider():
    """注入 exporter 且宿主 provider 先生效 ⇒ span 必须到达注入的 exporter（钉"孤儿 provider"半边）。"""
    foreign = _foreign_provider_without_otlp()
    sink = InMemorySpanExporter()
    assert _otlp_exporter_count(foreign) == 0

    kernel.init_tracing(enabled=True, service_name="d-lf-1-inj", exporter=sink)

    with kernel.start_span("d-lf-1.probe", attrs={"k": "v"}) as span:
        assert span.is_recording()
    kernel.force_flush()
    names = [s.name for s in sink.get_finished_spans()]
    assert "d-lf-1.probe" in names, (
        f"注入的 exporter 没收到 span ⇒ 挂在了被丢弃的自建 provider 上；实际收到={names}")
