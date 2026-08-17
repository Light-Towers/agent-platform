"""API 层 Pydantic 契约（类型安全，防幻觉式字段拼写）。

app 的查询/健康契约统一接入联邦网关的 shared_schemas，成为唯一事实来源：
- QueryRequest / HealthResponse 直接复用 shared_schemas，入站字段使用网关
  标准名（query / session_id）。旧字段名（question / thread_id）的双写兼容
  已于 2026-08-16 移除（U-1 收敛）。
- 其余 app 内部专用类型（CoordinationDecision / AdmissionDecision / McpServerConfig
  等）仍本文件定义，不属于跨服务联邦契约。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from shared_schemas import (
    HealthResponse as BaseHealthResponse,
)
from shared_schemas import (
    Priority,
)
from shared_schemas import (
    QueryRequest as BaseQueryRequest,
)

# 重新导出联邦类型，供 app 内部（routes.py 等）从 app.schemas 统一引用
__all__ = ["Capability", "HealthResponse", "Priority", "QueryRequest"]

Capability = Literal["search", "rag", "sql", "direct", "mcp"]


class QueryRequest(BaseQueryRequest):
    """联邦统一查询请求 + app 向后兼容别名。

    入站 JSON 同时接受网关标准名（query/session_id）与旧客户端名
    （question/thread_id）；内部统一以标准名（query/session_id）存储，
    routes.py 使用标准名访问。user_id/priority 沿用基类可选字段，
    app 仅覆盖默认值（user_id 默认 "default"、priority 默认 "normal"）。
    """

    model_config = ConfigDict(populate_by_name=True)

    # 覆盖基类字段，统一使用网关标准名 query（U-1 已收敛：旧字段名 question/
    # thread_id 的入站双写兼容于 2026-08-16 彻底移除，存量客户端须改用 query/
    # session_id）。内部 graph state 字段仍名为 question，与入站契约无关。
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户查询文本（网关标准名 query）",
    )
    session_id: str | None = Field(
        default=None,
        description="会话 ID（网关标准名 session_id）",
    )
    # 工作空间隔离键（优化 G）：跨会话记忆与 RAG 文档按 workspace 隔离；
    # 未传时记为 default（全局共享空间）。user_id 仅作辅助归属维度，不参与隔离。
    workspace_id: str = Field(default="default")
    # app 业务默认值：未传 user_id 时记为 default（基类为 None）
    user_id: str = Field(default="default")
    priority: Priority = Field(default="normal")


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


class HealthResponse(BaseHealthResponse):
    """联邦统一健康检查响应 + app 能力标志。

    复用 shared_schemas.HealthResponse（status: HealthStatus enum / version /
    dependencies），app 独有能力标志（coordination/admission/revert/...）已在
    共享契约中以可选字段提供，此处仅做显式再导出以保持对外形态一致。
    """


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
