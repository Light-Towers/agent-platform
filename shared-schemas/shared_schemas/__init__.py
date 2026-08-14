"""统一 Pydantic schema，deepagents 联邦网关 4 服务共享。

所有子服务（wenda-adapter / zhiku / kefu-adapter / deepagents 网关）
的 API 请求/响应均使用此包定义的 schema，确保跨服务类型安全。
"""

from shared_schemas.health import DependencyHealth, HealthResponse, HealthStatus
from shared_schemas.intent import IntentCandidate, IntentResult
from shared_schemas.query import Priority, QueryData, QueryRequest, QueryResponse
from shared_schemas.subagent import SubagentCall, SubagentResult

__all__ = [
    "DependencyHealth",
    "HealthResponse",
    "HealthStatus",
    "IntentCandidate",
    "IntentResult",
    "Priority",
    "QueryData",
    "QueryRequest",
    "QueryResponse",
    "SubagentCall",
    "SubagentResult",
]
