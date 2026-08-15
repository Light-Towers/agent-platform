# -*- coding: utf-8 -*-
"""
test_tracing.py —— M4 OTel 全链路追踪单测（方案 §8）。

验证：
1. **no-op 降级铁律**：未 init（或未启用 / 未装 SDK）时，start_span / traced_span /
   get_tracer 均不抛异常、零开销、不改变返回值；
2. **真实 span 路径**：init 时显式注入 ``InMemorySpanExporter``，能产生 span 且
   属性正确（config_hash / collection / request_id / user_query_hash 统一注入）；
3. **request_id 格式**与 **user_query_hash 稳定性**；
4. **幂等**：重复 init 不重复创建 provider / exporter。

【依赖策略】opentelemetry 为可选依赖（pyproject ``[project.optional-dependencies] tracing``）。
本文件对真实 SDK 路径使用 ``skipif`` 守卫：OTel 未安装时 no-op 用例照常运行，
真实 SDK 用例自动跳过 —— CI（``uv sync --frozen`` 不装 extra）也能全绿。
本测试**不连接真实 collector**，全部使用内存 exporter / no-op。
"""

import re

import pytest

from app.core import tracing


# ---------------------------------------------------------------------------
# OTel SDK 可用性探测（CI / 本地未装 extra 时跳过真实 SDK 用例）
# ---------------------------------------------------------------------------
try:
    # opentelemetry-sdk < 1.44：InMemorySpanExporter 在顶层 export 命名空间
    from opentelemetry.sdk.trace.export import InMemorySpanExporter  # noqa: F401

    HAVE_OTEL_SDK = True
except Exception:
    # opentelemetry-sdk >= 1.44：移入独立子模块 in_memory_span_exporter
    try:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: F401

        HAVE_OTEL_SDK = True
    except Exception:
        HAVE_OTEL_SDK = False

requires_sdk = pytest.mark.skipif(not HAVE_OTEL_SDK, reason="opentelemetry-sdk 未安装（可选 extra tracing）")


# ---------------------------------------------------------------------------
# 共享 fixture：每个用例前后重置模块状态，避免 init 幂等性污染跨用例断言
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_tracing():
    tracing._reset_for_tests()
    yield
    tracing._reset_for_tests()


# ===========================================================================
# 1) no-op 降级铁律（不依赖 OTel，CI 无 OTel 也必须通过）
# ===========================================================================
def test_is_tracing_enabled_false_by_default():
    assert tracing.is_tracing_enabled() is False
    assert tracing.is_initialized() is False


def test_get_tracer_without_init_returns_noop():
    tracer = tracing.get_tracer()
    with tracer.start_as_current_span("noop.span") as span:
        span.set_attribute("a", 1)
    tracer.start_span("noop.plain").end()


def test_start_span_without_init_does_not_raise():
    with tracing.start_span("noop.span", attrs={"k": "v"}) as span:
        span.set_attribute("a", 1)
        span.record_exception(ValueError("x"))


def test_decorator_without_init_passthrough():
    @tracing.traced_span("noop.deco")
    def add(a: int, b: int = 2) -> int:
        return a + b

    assert add(1) == 3
    assert add(1, 10) == 11


def test_decorator_without_init_does_not_swallow_exception():
    @tracing.traced_span("noop.deco.raise")
    def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        boom()


def test_init_empty_endpoint_is_noop():
    # 显式 enabled=True 但 endpoint 为空（且未注入 exporter）→ 必须 no-op
    tracer = tracing.init_tracing(enabled=True, otel_endpoint="")
    assert tracing.is_tracing_enabled() is False
    with tracing.start_span("noop.span") as span:
        span.set_attribute("a", 1)
    with tracer.start_as_current_span("noop.tracer") as span:
        span.set_attribute("b", 2)


def test_init_disabled_by_default_env_is_noop(monkeypatch):
    # 未设置 ZHANGUI_TRACE_ENABLED → 默认 false → no-op（即使 SDK 已装）
    monkeypatch.delenv("ZHANGUI_TRACE_ENABLED", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    tracing.init_tracing()
    assert tracing.is_tracing_enabled() is False


# ===========================================================================
# 2) request_id / user_query_hash 工具（不依赖 OTel）
# ===========================================================================
def test_request_id_format():
    request_id = tracing.generate_request_id()
    assert re.fullmatch(r"[0-9a-f]{12}", request_id)
    # 两次生成不同（uuid4 随机性）
    assert request_id != tracing.generate_request_id()


def test_user_query_hash_stable_and_deterministic():
    query = "HAK 180 烫金机怎么换烫印头"
    h1 = tracing.user_query_hash(query)
    h2 = tracing.user_query_hash(query)
    assert h1 == h2
    assert len(h1) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", h1)
    # 不同 query → 不同 hash
    assert h1 != tracing.user_query_hash("烫金机额定电压是多少")
    # 空串不抛异常
    assert tracing.user_query_hash("") == tracing.user_query_hash("")


# ===========================================================================
# 3) 真实 span 路径（需 opentelemetry-sdk；InMemorySpanExporter，不连 collector）
# ===========================================================================
@requires_sdk
def test_init_with_inmemory_exporter_produces_span():
    exporter = InMemorySpanExporter()
    tracing.init_tracing(enabled=True, exporter=exporter, config_hash="cfg-test", collection="col_test")

    with tracing.start_span("test.span", attrs={"foo": "bar"}) as span:
        span.set_attribute("baz", 1)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "test.span"
    attrs = dict(span.attributes)
    assert attrs["foo"] == "bar"
    assert attrs["baz"] == 1
    # 统一属性注入：config_hash / collection
    assert attrs["config_hash"] == "cfg-test"
    assert attrs["collection"] == "col_test"


@requires_sdk
def test_span_carries_request_context_attrs():
    exporter = InMemorySpanExporter()
    tracing.init_tracing(enabled=True, exporter=exporter)

    tracing.set_request_context(request_id="rid-abc", user_query_hash="uqh-xyz")
    with tracing.start_span("req.span"):
        pass

    span = exporter.get_finished_spans()[0]
    attrs = dict(span.attributes)
    assert attrs["request_id"] == "rid-abc"
    assert attrs["user_query_hash"] == "uqh-xyz"


@requires_sdk
def test_init_default_unified_attrs_present():
    # 不显式传 config_hash / collection → 自动兜底（读 milvus_config + yaml 配置）
    exporter = InMemorySpanExporter()
    tracing.init_tracing(enabled=True, exporter=exporter)

    with tracing.start_span("default.attrs"):
        pass

    span = exporter.get_finished_spans()[0]
    attrs = dict(span.attributes)
    assert len(attrs["config_hash"]) == 8  # sha256 前 8 位
    assert isinstance(attrs["collection"], str) and attrs["collection"]
    assert "request_id" not in attrs  # 未设置请求上下文时不出现


@requires_sdk
def test_decorator_real_span_with_dynamic_attrs():
    exporter = InMemorySpanExporter()
    tracing.init_tracing(enabled=True, exporter=exporter)

    @tracing.traced_span(
        "retrieval.test",
        attributes_fn=lambda *args, result=None, **kwargs: {"hits": len(result or [])},
    )
    def fake_search(state):
        return [1, 2, 3]

    result = fake_search({"q": "x"})
    assert result == [1, 2, 3]  # 不改变返回值

    span = exporter.get_finished_spans()[0]
    assert span.name == "retrieval.test"
    assert dict(span.attributes)["hits"] == 3


@requires_sdk
def test_decorator_records_exception_and_rethrows():
    exporter = InMemorySpanExporter()
    tracing.init_tracing(enabled=True, exporter=exporter)

    @tracing.traced_span("err.span")
    def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        boom()

    span = exporter.get_finished_spans()[0]
    assert span.name == "err.span"
    assert any(e.name == "exception" for e in span.events)


# ===========================================================================
# 4) 幂等：重复 init 不重复初始化 exporter / provider
# ===========================================================================
@requires_sdk
def test_init_is_idempotent():
    exporter1 = InMemorySpanExporter()
    tracer1 = tracing.init_tracing(enabled=True, exporter=exporter1)
    provider1 = tracing._provider

    # 第二次 init（即使传入不同的 exporter）应被幂等短路，不创建新 provider
    exporter2 = InMemorySpanExporter()
    tracer2 = tracing.init_tracing(enabled=True, exporter=exporter2)
    assert tracing._provider is provider1
    assert tracer2 is tracer1

    with tracing.start_span("idem.span"):
        pass

    # span 只进入第一个 exporter
    assert len(exporter1.get_finished_spans()) == 1
    assert len(exporter2.get_finished_spans()) == 0
