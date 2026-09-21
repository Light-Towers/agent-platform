"""middleware/：ExecutionContext 解析与校验（C1 落地点）。"""

from exhibition_agent.middleware.execution_context_middleware import (
    EXECUTION_CONTEXT_HEADER,
    AuthContextInvalidError,
    AuthContextMissingError,
    ExecutionContextError,
    RequestContextBrokenError,
    ScopeDeniedError,
    resolve_execution_context,
)

__all__ = [
    "ExecutionContextError",
    "AuthContextMissingError",
    "AuthContextInvalidError",
    "ScopeDeniedError",
    "RequestContextBrokenError",
    "resolve_execution_context",
    "EXECUTION_CONTEXT_HEADER",
]
