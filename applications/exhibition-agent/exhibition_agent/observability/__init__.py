"""observability/：trace 记录（C4 契约）+ OTel 分布式追踪 + 轻量 metrics + LLM 可观测后端抽象。"""

from exhibition_agent.observability.llm_obs import (
    LangfuseBackend,
    LangSmithBackend,
    LLMObsBackend,
    NoOpBackend,
    get_llm_obs_backend,
    reset_backend_cache,
)
from exhibition_agent.observability.metrics import (
    MetricsRegistry,
    get_default_registry,
)
from exhibition_agent.observability.otel import (
    extract_traceparent,
    get_current_traceparent,
    get_tracer_instance,
    init_observability,
    inject_traceparent,
    span,
    use_context,
)
from exhibition_agent.observability.trace import (
    TRACE_REQUIRED_FIELDS,
    InMemoryTraceRecorder,
    TraceRecord,
    TraceRecorder,
)

__all__ = [
    "TraceRecord",
    "TraceRecorder",
    "InMemoryTraceRecorder",
    "TRACE_REQUIRED_FIELDS",
    "MetricsRegistry",
    "get_default_registry",
    "init_observability",
    "span",
    "inject_traceparent",
    "extract_traceparent",
    "use_context",
    "get_current_traceparent",
    "get_tracer_instance",
    "LLMObsBackend",
    "NoOpBackend",
    "LangfuseBackend",
    "LangSmithBackend",
    "get_llm_obs_backend",
    "reset_backend_cache",
]
