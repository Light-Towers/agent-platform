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
