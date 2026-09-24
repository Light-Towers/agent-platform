"""OTel no-op 降级路径测试。

本机未装 opentelemetry SDK，测 no-op 降级路径（记忆 feedback_otel-sdk-missing）。
覆盖：init_otel 幂等 / 采样率校验 / no-op 降级 / traceparent 透传 / 脱敏 / force_flush。
"""

from __future__ import annotations

from agent_core.tracing import _NoOpTracer

from agent_runtime.otel import (
    force_flush,
    get_otel_tracer,
    init_otel,
    parse_traceparent,
    redact_question,
)


def test_get_tracer_uninit_returns_noop():
    """未初始化时 get_otel_tracer 返回 no-op tracer。"""
    tracer = get_otel_tracer()
    assert isinstance(tracer, _NoOpTracer)


def test_init_exporter_none_sets_noop():
    """exporter='none' 显式降级为 no-op。"""
    init_otel(exporter="none")
    tracer = get_otel_tracer()
    assert isinstance(tracer, _NoOpTracer)


def test_init_without_sdk_sets_noop():
    """OTel SDK 未安装时 init_otel 降级为 no-op（本机无 SDK 的默认路径）。"""
    init_otel(exporter="otlp", endpoint="http://localhost:4318")
    tracer = get_otel_tracer()
    assert isinstance(tracer, _NoOpTracer)


def test_init_idempotent():
    """多次 init_otel 不抛异常（幂等）。"""
    init_otel(exporter="none")
    init_otel(exporter="none")
    init_otel(exporter="otlp", endpoint="")
    tracer = get_otel_tracer()
    assert isinstance(tracer, _NoOpTracer)


def test_init_invalid_sampling_rate_clamped():
    """非法采样率不抛异常（内部钳制到 1.0）。"""
    init_otel(exporter="none", sampling_rate=-0.5)
    init_otel(exporter="none", sampling_rate=2.0)
    tracer = get_otel_tracer()
    assert isinstance(tracer, _NoOpTracer)


def test_parse_traceparent_none_header():
    """空 header 返回 None。"""
    assert parse_traceparent(None) is None
    assert parse_traceparent("") is None


def test_parse_traceparent_without_sdk():
    """OTel SDK 未安装时 parse_traceparent 返回 None。"""
    result = parse_traceparent("00-abcdef1234567890abcdef1234567890-1234567890abcdef-01")
    assert result is None


def test_redact_question_no_full_text():
    """脱敏：返回长度 + 哈希，不含全文。"""
    question = "我的订单1001的物流状态如何？"
    result = redact_question(question)
    assert "question_length" in result
    assert "question_hash" in result
    assert result["question_length"] == len(question)
    assert isinstance(result["question_hash"], str)
    assert question not in str(result)


def test_redact_question_consistent_hash():
    """相同问题哈希一致。"""
    q = "重复问题"
    assert redact_question(q)["question_hash"] == redact_question(q)["question_hash"]


def test_redact_question_different_questions_different_hash():
    """不同问题哈希不同。"""
    assert redact_question("问题A")["question_hash"] != redact_question("问题B")["question_hash"]


def test_force_flush_noop_without_tracer():
    """未初始化时 force_flush 不抛异常。"""
    force_flush()


def test_force_flush_after_init():
    """初始化后 force_flush 不抛异常。"""
    init_otel(exporter="none")
    force_flush()


def test_noop_tracer_span_not_recording():
    """no-op span 的 is_recording 返回 False。"""
    tracer = get_otel_tracer()
    span = tracer.start_span("test-span")
    assert span.is_recording() is False


def test_noop_tracer_context_manager():
    """no-op tracer 的 start_as_current_span 可作上下文管理器。"""
    tracer = get_otel_tracer()
    with tracer.start_as_current_span("test-span") as span:
        assert span.is_recording() is False
        span.set_attribute("key", "value")
        span.set_status("OK")
