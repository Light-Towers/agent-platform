"""健康检查 schema。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

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


class CacheStatsReport(BaseModel):
    """语义缓存的命中率与分账计数（ADR-0013 Stage 4 判据「命中率可在指标或 health 读到」）。

    为什么是一个**带默认值的固定形状**，而不是把 `get_stats()` 的原样 dict 摊出去：
    后端计数器只在"被记过"时才出现在 `CacheStats.snapshot()` 里，两个后端的键集合也不齐
    （disabled 从不记 `l1_hit/l2_hit/null_hit/miss`）⇒ 直接透传的话，`CACHE_BACKEND` 从
    valkey 切到 disabled、或冷启动还没命中时，**监控事件的键集合会静默变化**——读监控的人
    只会看到"某个计数消失了"，看不出那是"没发生"还是"没上报"。这是本仓最难查的那一类
    （"装了但没接上"的监控面版本）。固定形状把"没发生"和"没上报"分开了：这里永远是全量键、
    缺省 0。

    `from_counts` 对**未知计数名静默忽略**而不是抛：/health 是免鉴权探针路径，不能因为
    后端新加了一个计数器就把探针打成 500。代价是"新计数没人上报"这件事不由运行时管，
    改由常驻门禁管（`tests/governance/test_cache_stats_contract.py`：两个后端能产出的
    计数名必须都在本模型里、本模型的每个计数字段必须有生产者）。
    """

    backend: str = Field("", description="产生这份计数的后端（valkey / disabled）")
    scope: str = Field("", description="流水线分区（agent_server / federation），不是隔离维度")
    total: int = Field(0, description="查询总次数")
    hit_rate: float = Field(0.0, description="命中率 =（l1_hit+l2_hit+null_hit）/ total；total=0 时为 0.0")
    l1_hit: int = Field(0, description="L1 精确命中（不需要向量）")
    l2_hit: int = Field(0, description="L2 语义命中")
    null_hit: int = Field(0, description="负缓存命中（同样省掉一次后端查询）")
    miss: int = Field(0, description="未命中")
    error: int = Field(0, description="后端调用异常次数（fail-open 已按未命中处理）")
    skipped_no_tenant: int = Field(0, description="空租户 fail-closed 跳过次数")
    skipped_unsafe_tag: int = Field(0, description="TAG 含非法字符被拒绝的写入次数")
    skipped_pii: int = Field(0, description="写侧 PII 门禁拦下的写入次数")
    dropped_writes: int = Field(0, description="写队列满/关闭中被丢弃的写入次数")
    embedding_error: int = Field(0, description="embedding 缺失/维度不符导致跳过 L2 的次数")
    l2_unavailable: int = Field(0, description="L2 面不可用（索引/模块缺失）次数")
    index_missing: int = Field(0, description="检索时索引不存在的次数")

    @classmethod
    def from_counts(cls, counts: Mapping[str, Any] | None) -> "CacheStatsReport":
        """按字段名取数，缺省填 0/空串，未知键忽略。"""
        data = dict(counts or {})
        return cls(**{k: data[k] for k in cls.model_fields if k in data})


class HealthResponse(BaseModel):
    """统一健康检查响应。"""

    status: HealthStatus = Field(..., description="服务整体健康状态")
    version: str = Field(..., description="服务版本号")
    dependencies: list[DependencyHealth] = Field(default_factory=list, description="各依赖健康状态")
    # 以下为各服务可选贡献的能力标志（零破坏：默认 False/None，旧调用方不受影响）
    storage: str | None = Field(None, description="存储后端（postgres/memory 等）")
    llm: bool = Field(False, description="LLM 可用")
    search: bool = Field(False, description="联网搜索可用")
    # 归属说明（2026-10-28 批次 5）：这一位只该由**持有业务库连接**的服务上报（现：
    # nl2sql-service 报它的 dw 方言）。agent_server 此前也在报，但它读的那份 DSN 指**平台库**，
    # 等于拿“平台能连自己的库”充当问数读数（假灯）⇒ 已退役，见 ADR-0011 的后续修订。
    sql_backend: str | None = Field(None, description="Text-to-SQL 数据面方言（由持有业务库的服务上报；无该面为 null）")
    coordination: bool = Field(False, description="会话并发协调（coordinator）启用")
    admission: bool = Field(False, description="准入限流（admission）启用")
    revert: bool = Field(False, description="对话回退（revert）启用")
    otel: bool = Field(False, description="OpenTelemetry 追踪启用")
    # R11（观测方案 §3.2）：上报 kernel 状态机真值，区分"显式关"与"坏了"；
    # 只增字段不改形状（消费者审计见方案 §5），旧调用方不受影响。
    otel_status: str | None = Field(
        None,
        description="OTel 观测状态机真值：ACTIVE / DEGRADED / DISABLED / UNINITIALIZED（DEGRADED 时 reason 记真因）",
    )
    mcp: bool = Field(False, description="MCP 工具启用")
