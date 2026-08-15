"""W3C traceparent 跨服务上下文传播（已上提到 agent_core.tracing_propagation）。

此文件保留为 re-export shim，兼容现有 from agent.tracing.trace_propagation import ... 调用方。
"""

from agent_core.tracing_propagation import (  # noqa: F401
    extract_traceparent,
    get_current_traceparent,
    inject_traceparent,
    use_context,
)
