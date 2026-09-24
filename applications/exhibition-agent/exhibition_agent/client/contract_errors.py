"""C2 契约客户端异常：按错误码表映射。

每个异常携带 error_code / http_status / message / retryable，
供上层（skill / supervisor / trace）按契约语义处理。

retryable 为契约语义标记（指示错误是否可重试）。WarehouseClient.invoke 对
UpstreamError / RateLimitedError 做有界指数退避重试；其余 retryable=False 的异常
不重试。调用方需确保 skill 幂等（当前所有 skill 均为只读，重试安全）。
"""

from __future__ import annotations

from exhibition_agent.contract.error_codes import ErrorCode


class ContractError(Exception):
    """契约错误基类。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        super().__init__(f"[{code.value}] {message}")


class AuthError(ContractError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code, message, 401, retryable=False)


class ScopeDeniedError(ContractError):
    def __init__(self, message: str = "越权访问") -> None:
        super().__init__(ErrorCode.SCOPE_DENIED, message, 403, retryable=False)


class EgressDeniedError(ContractError):
    def __init__(self, message: str = "出域策略未过") -> None:
        super().__init__(ErrorCode.EGRESS_DENIED, message, 403, retryable=False)


class KnowledgeNotPublishedError(ContractError):
    def __init__(self, message: str = "知识未发布") -> None:
        super().__init__(ErrorCode.KNOWLEDGE_NOT_PUBLISHED, message, 404, retryable=False)


class MetricPendingError(ContractError):
    """METRIC_NOT_VERIFIED / METRIC_BLOCKED → 只能答"该指标待接入"（INV-10）。"""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code, message, 422, retryable=False)


class DataNotConnectedError(ContractError):
    def __init__(self, message: str = "数据源未接入") -> None:
        super().__init__(ErrorCode.DATA_NOT_CONNECTED, message, 422, retryable=False)


class RateLimitedError(ContractError):
    def __init__(self, message: str = "限流", retry_after_ms: int | None = None) -> None:
        super().__init__(ErrorCode.RATE_LIMITED, message, 429, retryable=True)
        # warehouse 侧 Retry-After 头解析后的毫秒数（优先于客户端指数退避）
        self.retry_after_ms = retry_after_ms


class UpstreamError(ContractError):
    def __init__(self, message: str = "上游故障") -> None:
        super().__init__(ErrorCode.UPSTREAM_ERROR, message, 502, retryable=True)


class ReadinessMissingError(ContractError):
    """缺 readiness 的数值响应 → 判 fail（不是 warn）。"""

    def __init__(self, message: str = "数值响应缺 readiness，判 fail") -> None:
        super().__init__(ErrorCode.INTERNAL, message, 500, retryable=False)


class GroundednessError(ContractError):
    """知识类响应缺 citations → 平台侧拒绝展示（groundedness，契约 v1.1 §C2）。"""

    def __init__(self, message: str = "知识类响应缺 citations，拒绝展示") -> None:
        super().__init__(ErrorCode.INTERNAL, message, 500, retryable=False)
