"""API 层 Pydantic 契约（类型安全，防幻觉式字段拼写）。"""

from typing import Literal

from pydantic import BaseModel, Field

Capability = Literal["search", "rag", "sql", "direct", "mcp"]

Priority = Literal["high", "normal", "low"]


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # 仅在未启用 API_KEY 认证时生效；启用认证时服务端忽略该值（防会话劫持）
    thread_id: str | None = None
    user_id: str = "default"
    priority: Priority = "normal"


class ImportResponse(BaseModel):
    doc_id: str
    source: str
    chunks: int


class SqlTrainRequest(BaseModel):
    ddl: str | None = None
    documentation: str | None = None
    question: str | None = None
    sql: str | None = None


class SqlTrainResponse(BaseModel):
    ddl_stored: bool = False
    doc_stored: bool = False
    example_stored: bool = False


class HealthResponse(BaseModel):
    status: str
    storage: Literal["postgres", "memory"]
    llm: bool
    search: bool
    sql_backend: str
    coordination: bool = False
    admission: bool = False
    revert: bool = False
    otel: bool = False
    mcp: bool = False


class RevertRequest(BaseModel):
    session_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)


class RevertResponse(BaseModel):
    session_id: str
    checkpoint_id: str
    context_summary: str
    reverted_at: str


class AdmissionDecision(BaseModel):
    status: Literal["admitted", "queued", "rejected"]
    queue_position: int | None = None
    priority: Priority = "normal"
    estimated_wait_seconds: float | None = None
    reason: str | None = None


class CoordinationDecision(BaseModel):
    decision_type: Literal["serialize", "coalesce", "queue", "reject"]
    request_id: str
    wait_seconds: float = 0.0


class McpServerConfig(BaseModel):
    server_id: str
    transport: Literal["stdio", "sse"]
    endpoint: str
    tool_allowlist: list[str] = []
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
