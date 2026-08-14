"""健康检查 schema。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DependencyHealth(BaseModel):
    """单个依赖的健康状态。"""

    name: str = Field(..., description="依赖名称（如 mysql / milvus / neo4j）")
    status: HealthStatus = Field(..., description="依赖健康状态")
    latency_ms: float | None = Field(None, description="依赖探活延迟（毫秒）")
    detail: str | None = Field(None, description="额外信息（如错误描述）")


class HealthResponse(BaseModel):
    """统一健康检查响应。"""

    status: HealthStatus = Field(..., description="服务整体健康状态")
    version: str = Field(..., description="服务版本号")
    dependencies: list[DependencyHealth] = Field(default_factory=list, description="各依赖健康状态")
    # 以下为各服务可选贡献的能力标志（零破坏：默认 False/None，旧调用方不受影响）
    storage: str | None = Field(None, description="存储后端（postgres/memory 等）")
    llm: bool = Field(False, description="LLM 可用")
    search: bool = Field(False, description="联网搜索可用")
    sql_backend: str | None = Field(None, description="Text-to-SQL 后端标识")
    coordination: bool = Field(False, description="会话并发协调（coordinator）启用")
    admission: bool = Field(False, description="准入限流（admission）启用")
    revert: bool = Field(False, description="对话回退（revert）启用")
    otel: bool = Field(False, description="OpenTelemetry 追踪启用")
    mcp: bool = Field(False, description="MCP 工具启用")
