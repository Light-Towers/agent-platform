"""agent-runtime 运行时契约（Plan-F 从 app/schemas.py 迁移）。

app 内部运行时专用类型（AdmissionDecision / CoordinationDecision /
RevertResult / McpServerConfig / McpToolResult 等）不属于跨服务联邦契约
（shared-schemas 只承载联邦网关契约），故随实现迁入 agent-runtime 同包，
保持"类型与实现同源"的高内聚。app/schemas.py 负责 re-export 兼容旧引用。
"""

from typing import Literal

from pydantic import BaseModel, Field
from shared_schemas import Priority

# TD-10：准入状态枚举常量（避免散点字符串字面量写死进 SQL / 比较逻辑）
ADMISSION_ADMITTED = "admitted"
ADMISSION_QUEUED = "queued"
ADMISSION_REJECTED = "rejected"


class AdmissionDecision(BaseModel):
    status: Literal[ADMISSION_ADMITTED, ADMISSION_QUEUED, ADMISSION_REJECTED]
    queue_position: int | None = None
    priority: Priority = "normal"
    estimated_wait_seconds: float | None = None
    reason: str | None = None


class CoordinationDecision(BaseModel):
    decision_type: Literal["serialize", "queue", "reject"]
    request_id: str
    wait_seconds: float = 0.0


class McpServerConfig(BaseModel):
    server_id: str
    transport: Literal["stdio", "sse"]
    endpoint: str
    tool_allowlist: list[str] = Field(default_factory=list)
    timeout_seconds: float = 30.0
    enabled: bool = False


class McpToolResult(BaseModel):
    success: bool
    evidence: list[str] = []
    error: str | None = None
    duration_ms: int = 0


class RevertResult(BaseModel):
    success: bool
    session_id: str
    checkpoint_id: str
    context_summary: str
    error: str | None = None
