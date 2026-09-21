"""最小 skill 协议（只读）。

Skill 只经 WarehouseClient 调领域 API（INV-6），不直连库、不写操作。
INV-10 落地：收到 MetricPendingError → 答"该指标待接入"，不触 L3、不生成 SQL。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.contract.envelope import (
    Citation,
    DataClassification,
    EgressDecision,
    Readiness,
    Source,
)
from exhibition_agent.contract.execution_context import ExecutionContext


@dataclass
class SkillResult:
    """skill 执行结果（供 supervisor 组装最终回答）。"""

    answer: str
    readiness: Readiness
    classification: DataClassification
    sources: list[Source] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retrieval_hit_ids: list[str] = field(default_factory=list)
    error_code: str | None = None
    egress_decision: EgressDecision = EgressDecision.ALLOW
    model: str = "stub-private-qwen"
    cost: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillContext:
    """skill 运行上下文（由 supervisor 注入）。"""

    execution_context: ExecutionContext
    execution_context_header: str
    warehouse_client: WarehouseClient
    context_mode: str = "jwt"
    extra_headers: dict[str, str] | None = None


class BaseSkill(ABC):
    """只读 skill 基类。"""

    name: str
    description: str

    @abstractmethod
    async def run(self, params: dict[str, Any], ctx: SkillContext) -> SkillResult:
        """执行 skill（只读）。"""
        raise NotImplementedError
