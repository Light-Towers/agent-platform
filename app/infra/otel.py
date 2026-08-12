"""OpenTelemetry 分布式追踪集成。

- 遵循 GenAI 语义约定 gen_ai.*
- exporter 可插拔（otlp/jaeger/console/none）
- 与 Langfuse 共存，不替代
- W3C traceparent 透传
- 数据脱敏（不含问题全文）
- 默认 false（opt-in）
"""

import hashlib
import logging
from typing import Literal

logger = logging.getLogger(__name__)

# 可选导入 opentelemetry
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_ON,
        TraceIdRatioBasedSampler,
    )

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

_tracer = None


class _NoOpSpan:
    """空上下文管理器（OTel 未启用/未安装时）。"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def set_attribute(self, key, value):
        pass

    def record_exception(self, exc):
        pass

    def add_event(self, name, attributes=None):
        pass


class _NoOpTracer:
    """空 tracer（OTel 未启用/未安装时）。"""

    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()

    def start_span(self, name, **kwargs):
        return _NoOpSpan()


def init_otel(
    exporter: Literal["otlp", "jaeger", "console", "none"] = "otlp",
    endpoint: str = "",
    sampling_rate: float = 1.0,
    service_name: str = "agent-platform",
) -> None:
    """初始化 OTel tracer provider。"""
    global _tracer

    if not _OTEL_AVAILABLE:
        logger.warning("OTEL_INIT_FAILED: opentelemetry SDK not installed")
        _tracer = _NoOpTracer()
        return

    if exporter == "none":
        _tracer = _NoOpTracer()
        return

    # 采样率校验
    if not 0.0 <= sampling_rate <= 1.0:
        logger.warning("OTEL_SAMPLING_INVALID: %s, using 1.0", sampling_rate)
        sampling_rate = 1.0

    try:
        sampler = (
            ALWAYS_ON if sampling_rate >= 1.0 else TraceIdRatioBasedSampler(sampling_rate)
        )
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource, sampler=sampler)

        if exporter == "console":
            from opentelemetry.sdk.trace.export import (
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )

            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        elif exporter == "otlp":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter_obj = OTLPSpanExporter(endpoint=endpoint or None)
            provider.add_span_processor(BatchSpanProcessor(exporter_obj))
        elif exporter == "jaeger":
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter_obj = JaegerExporter()
            provider.add_span_processor(BatchSpanProcessor(exporter_obj))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("agent-platform")
        logger.info("OTel initialized: exporter=%s sampling=%s", exporter, sampling_rate)

    except Exception:
        logger.warning("OTEL_INIT_FAILED", exc_info=True)
        _tracer = _NoOpTracer()


def get_otel_tracer():
    """返回当前 tracer（未初始化时 NoOp）。"""
    if _tracer is None:
        return _NoOpTracer()
    return _tracer


def parse_traceparent(header: str | None):
    """解析 W3C traceparent header，返回 OTel Context 或 None。"""
    if not header or not _OTEL_AVAILABLE:
        return None
    try:
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextFormat,
        )
        from opentelemetry import context as otel_context

        ctx = TraceContextFormat().extract({"traceparent": header})
        return ctx
    except Exception:
        return None


def redact_question(question: str) -> dict:
    """脱敏：返回问题长度 + 哈希摘要，不含全文。"""
    return {
        "question_length": len(question),
        "question_hash": hashlib.sha256(question.encode()).hexdigest()[:16],
    }


def force_flush() -> None:
    """关闭前 flush 所有 span。"""
    if _tracer is not None and _OTEL_AVAILABLE:
        try:
            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush()
        except Exception:
            pass
