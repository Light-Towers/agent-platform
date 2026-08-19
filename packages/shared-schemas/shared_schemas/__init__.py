"""统一 Pydantic schema，deepagents 联邦网关 4 服务共享。

所有子服务（wenda-data-agent / zhiku / kefu-service / deepagents 网关）
的 API 请求/响应均使用此包定义的 schema，确保跨服务类型安全。
（原 wenda-adapter 已于 2026-08 退役，由 wenda-data-agent 直连替代。）
"""

from shared_schemas.health import DependencyHealth, HealthResponse, HealthStatus
from shared_schemas.intent import IntentCandidate, IntentResult
from shared_schemas.query import Priority, QueryData, QueryRequest, QueryResponse
from shared_schemas.subagent import SubagentCall, SubagentResult
from shared_schemas.thread import THREAD_STATE_VERSION, ThreadState, empty_thread_state, message_dict

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
    "THREAD_STATE_VERSION",
    "ThreadState",
    "empty_thread_state",
    "message_dict",
]
