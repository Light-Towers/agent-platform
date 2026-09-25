"""C2 错误码表 + HTTP 映射。

来源：跨项目接口契约 v1.1 §C2 错误响应表。
INV-10 落地点：METRIC_NOT_VERIFIED / METRIC_BLOCKED → 平台只能答"该指标待接入"。
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """契约 C2 错误码（与 HTTP 状态码一一对应）。"""

    AUTH_CONTEXT_MISSING = "AUTH_CONTEXT_MISSING"
    AUTH_CONTEXT_INVALID = "AUTH_CONTEXT_INVALID"
    SCOPE_DENIED = "SCOPE_DENIED"
    EGRESS_DENIED = "EGRESS_DENIED"
    KNOWLEDGE_NOT_PUBLISHED = "KNOWLEDGE_NOT_PUBLISHED"
    METRIC_NOT_VERIFIED = "METRIC_NOT_VERIFIED"
    METRIC_BLOCKED = "METRIC_BLOCKED"
    DATA_NOT_CONNECTED = "DATA_NOT_CONNECTED"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    REQUEST_CONTEXT_BROKEN = "REQUEST_CONTEXT_BROKEN"
    INTERNAL = "INTERNAL"


ERROR_CODE_HTTP_MAP: dict[ErrorCode, int] = {
    ErrorCode.AUTH_CONTEXT_MISSING: 401,
    ErrorCode.AUTH_CONTEXT_INVALID: 401,
    ErrorCode.SCOPE_DENIED: 403,
    ErrorCode.EGRESS_DENIED: 403,
    ErrorCode.KNOWLEDGE_NOT_PUBLISHED: 404,
    ErrorCode.METRIC_NOT_VERIFIED: 422,
    ErrorCode.METRIC_BLOCKED: 422,
    ErrorCode.DATA_NOT_CONNECTED: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.REQUEST_CONTEXT_BROKEN: 400,
    ErrorCode.INTERNAL: 500,
}

METRIC_PENDING_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.METRIC_NOT_VERIFIED, ErrorCode.METRIC_BLOCKED}
)
"""命中这两个码 → 平台只能答"该指标待接入"，禁止 L3 自算（INV-10）。"""

PENDING_ANSWER_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.METRIC_NOT_VERIFIED, ErrorCode.METRIC_BLOCKED, ErrorCode.DATA_NOT_CONNECTED}
)
"""契约 v1.1 §2.6：命中这三码 → 答"该指标待接入"（DATA_NOT_CONNECTED 并入 INV-10 回归）。"""

PENDING_ANSWER: str = "该指标待接入"
"""INV-10 确定性回答，禁止 LLM 自造口径。"""
