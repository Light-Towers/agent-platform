"""统一 Pydantic schema，deepagents 联邦网关 4 服务共享。

所有子服务（wenda-adapter / zhiku / kefu-adapter / deepagents 网关）
的 API 请求/响应均使用此包定义的 schema，确保跨服务类型安全。
"""

from shared_schemas.query import QueryRequest, QueryResponse, QueryData
from shared_schemas.health import HealthResponse, HealthStatus, DependencyHealth
from shared_schemas.intent import IntentResult, IntentCandidate
from shared_schemas.subagent import SubagentCall, SubagentResult

__all__ = [
    "QueryRequest",
    "QueryResponse",
    "QueryData",
    "HealthResponse",
    "HealthStatus",
    "DependencyHealth",
    "IntentResult",
    "IntentCandidate",
    "SubagentCall",
    "SubagentResult",
]
