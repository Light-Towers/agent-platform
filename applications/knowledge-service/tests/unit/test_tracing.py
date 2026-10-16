# -*- coding: utf-8 -*-
"""
test_tracing.py —— M4 OTel 全链路追踪单测（方案 §8）。

验证：
1. **no-op 降级铁律**：未 init（或未启用 / 未装 SDK）时，start_span / traced_span /
   get_tracer 均不抛异常、零开销、不改变返回值；
2. **真实 span 路径**：init 时显式注入 ``InMemorySpanExporter``，能产生 span 且
   属性正确（config_hash / collection / request_id / user_query_hash 统一注入）；
3. **request_id 格式**与 **user_query_hash 稳定性**；
4. **幂等**：重复 init 不重复创建 provider / exporter；
5. **文档面钉桩**：``.env.example`` 声明的观测键名必须等于 kernel 实际读取的 ``ENV_*``。

【依赖策略】opentelemetry 为可选依赖（pyproject ``[project.optional-dependencies] tracing``）。
本文件对真实 SDK 路径使用 ``skipif`` 守卫：OTel 未安装时 no-op 用例照常运行，
真实 SDK 用例自动跳过 —— CI（``uv sync --frozen`` 不装 extra）也能全绿。
本测试**不连接真实 collector**，全部使用内存 exporter / no-op。
"""

import re
from pathlib import Path

# 私有状态断言用（_provider 不在 shim 重导出面内）：直取 kernel 模块本体
import agent_core.tracing as _kernel  # noqa: E402
import pytest

from knowledge_service.core import tracing

# ---------------------------------------------------------------------------
# OTel SDK 可用性探测（CI / 本地未装 extra 时跳过真实 SDK 用例）
# ---------------------------------------------------------------------------
try:
    # opentelemetry-sdk < 1.44：InMemorySpanExporter 在顶层 export 命名空间
    from opentelemetry.sdk.trace.export import InMemorySpanExporter  # noqa: F401

    HAVE_OTEL_SDK = True
except ImportError:
    # opentelemetry-sdk >= 1.44：移入独立子模块 in_memory_span_exporter
    try:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: F401

        HAVE_OTEL_SDK = True
    except ImportError:
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
    # 未设置**内核真正读取的**开关 → 默认 false → no-op（即使 SDK 已装）。
    # endpoint 故意给非空值：让"no-op"的唯一成因是开关默认关，而不是"没配端点"。
    # 键名取自 _kernel.ENV_TRACE_ENABLED 而非写死字符串 —— 它不在 kernel.__all__ 内，
    # shim 的 ``import *`` 不会重导出；而写死字符串正是 2026-09-23 那次改名把本用例
    # 跟着改成 KNOWLEDGE_TRACE_ENABLED（一个自诞生起就没有读取方的键）的成因。
    monkeypatch.delenv(_kernel.ENV_TRACE_ENABLED, raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    tracing.init_tracing()
    assert tracing.is_tracing_enabled() is False


@requires_sdk
def test_env_trace_enabled_true_really_enables(monkeypatch):
    """反向对照：同一个键置 true ⇒ 确实启用。

    没有这条，上一条"默认关"可能只是在断言一个**根本不起作用**的键的默认值
    （2026-09-23~2026-10-16 期间正是这种状态：文档让人去设 KNOWLEDGE_TRACE_ENABLED，
    而它无人读取，所以"照文档开了"和"没开"读数完全一样）。
    """
    monkeypatch.setenv(_kernel.ENV_TRACE_ENABLED, "true")
    exporter = InMemorySpanExporter()
    # 显式传空 endpoint：只靠注入的 exporter 导出，避免继承本机真实 OTLP 端点
    tracing.init_tracing(otel_endpoint="", exporter=exporter)
    assert tracing.is_tracing_enabled() is True

    with tracing.start_span("env.switch.span"):
        pass
    assert [s.name for s in exporter.get_finished_spans()] == ["env.switch.span"]


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
def test_init_default_unified_attrs_present(monkeypatch):
    # S1 内核抽取后契约：config_hash / collection 由宿主注入，缺省按中性环境变量
    # 回退（内核不再读宿主 milvus_config/yaml）。本用例钉住回退路径：
    # 以 env 模拟宿主注入（env 名即内核 ENV_* 常量），无 env 时为空串。
    monkeypatch.setenv("AGENT_CORE_CONFIG_HASH", "a1b2c3d4")
    monkeypatch.setenv("AGENT_CORE_COLLECTION", "chunks_test")
    exporter = InMemorySpanExporter()
    tracing.init_tracing(enabled=True, exporter=exporter)

    with tracing.start_span("default.attrs"):
        pass

    span = exporter.get_finished_spans()[0]
    attrs = dict(span.attributes)
    assert attrs["config_hash"] == "a1b2c3d4"  # env 回退生效（非空且透传）
    assert attrs["collection"] == "chunks_test"
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
    provider1 = _kernel._provider

    # 第二次 init（即使传入不同的 exporter）应被幂等短路，不创建新 provider
    exporter2 = InMemorySpanExporter()
    tracer2 = tracing.init_tracing(enabled=True, exporter=exporter2)
    assert _kernel._provider is provider1
    assert tracer2 is tracer1

    with tracing.start_span("idem.span"):
        pass

    # span 只进入第一个 exporter
    assert len(exporter1.get_finished_spans()) == 1
    assert len(exporter2.get_finished_spans()) == 0


# ===========================================================================
# 5) 文档面钉桩：.env.example 里的观测两键必须就是代码实际读取的键名
# ===========================================================================
_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _active_env_keys(text: str) -> list[str]:
    """取"真正会生效"的键（跳过注释行）——注释里提旧键名是有意留痕，不算声明。"""
    return [
        line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line and not line.lstrip().startswith("#")
    ]


def test_env_example_observability_keys_are_read_by_code():
    """钉住 `.env.example` 声明的服务名/开关键 == kernel 的 ``ENV_*`` 常量。

    `37d93427`（2026-09-23）的 ZHANGUI_*→KNOWLEDGE_* 改名只动了文档面：当时 KS 的
    ``core/tracing.py`` 已是纯 shim，读取方早在 2026-08-21 就换成 kernel 中性键
    ⇒ 新键名自诞生起无人读取，照文档设值会"以为开了、其实没开"。
    check_doc_sync 只核路径存在性，核不出这类漂移，故在此兜住这处已实证缺口。
    """
    keys = _active_env_keys(_ENV_EXAMPLE.read_text(encoding="utf-8-sig"))

    assert _kernel.ENV_TRACE_ENABLED in keys, f"缺少开关键 {_kernel.ENV_TRACE_ENABLED}"
    assert _kernel.ENV_SERVICE_NAME in keys, f"缺少服务名键 {_kernel.ENV_SERVICE_NAME}"

    known = {_kernel.ENV_TRACE_ENABLED, _kernel.ENV_SERVICE_NAME}
    stray = [k for k in keys if k.endswith(("TRACE_ENABLED", "SERVICE_NAME")) and k not in known]
    assert not stray, f"以下键无任何读取方，删掉或换成 {sorted(known)}：{stray}"
