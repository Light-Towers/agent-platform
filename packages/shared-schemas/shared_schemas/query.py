"""统一查询请求/响应 schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Priority = Literal["high", "normal", "low"]

CONTRACT_VERSION = "1.0"


class QueryRequest(BaseModel):
    """统一查询请求（所有子服务共用）。"""

    query: str = Field(..., min_length=1, max_length=4000, description="用户查询文本（全局上限 4000；子服务可按业务收窄）")
    tenant_id: str | None = Field(None, description="租户 ID（多租户隔离）")
    trace_id: str | None = Field(None, description="W3C traceparent（跨服务链路追踪）")
    # 2026-10-19 U-1 销项：旧字段名 thread_id 的兼容 alias 已删（取证见
    # docs/plans/plan-u1-query-request-alias-removal-2026-10-19.md——无真实外部生产者，
    # 唯一消费者是自家契约测试）。旧客户端发 thread_id 将被 pydantic 默认 extra=ignore
    # 静默忽略（session_id=None），不再映射。
    session_id: str | None = Field(None, description="会话 ID（对话状态隔离）")
    context: dict[str, Any] = Field(default_factory=dict, description="额外上下文（如上传文件路径）")
    # 以下为 app（统一 Agent 平台）贡献的可选扩展，向后兼容：旧调用方不传亦工作
    priority: Priority | None = Field(None, description="请求优先级（admission 限流用）")
    user_id: str | None = Field(None, description="用户标识（审计/配额用）")
    version: str = Field(CONTRACT_VERSION, description="契约版本号（缺省 1.0，向后兼容）")


class QueryData(BaseModel):
    """查询返回的结构化数据（各子服务自定义 content）。"""

    content: Any | None = Field(None, description="结构化数据内容（各子服务自定义）")
    source: str | None = Field(None, description="数据来源标识（如 mysql / milvus / neo4j）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="数据元信息")


class QueryResponse(BaseModel):
    """统一查询响应（所有子服务共用）。"""

    answer: str = Field(..., description="自然语言回答")
    data: QueryData | None = Field(None, description="结构化数据（可选）")
    trace_id: str | None = Field(None, description="W3C traceparent（回传给网关关联 span）")
    latency_ms: float | None = Field(None, description="处理延迟（毫秒）")
    intent: str | None = Field(None, description="命中的意图标签（可选）")
    fallback: bool = Field(False, description="是否走了降级路径")
    version: str = Field(CONTRACT_VERSION, description="契约版本号（缺省 1.0，向后兼容）")
