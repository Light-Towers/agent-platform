"""§17.5 Model Router 桩（不接真实 LLM / 真模型）。

Agent 不得自选模型，统一由 Model Router 决策。
路由输入：数据分级 + 出域决策 + 任务类型 + 模型能力 + 延迟 + 成本 + 企业配置。
出域策略未过 → 直接拒绝（EGRESS_DENIED），不得降级到云模型。

本模块是桩：返回固定模型标识 + 零成本，供 trace 记录。
生产注入真实 Model Router 实现后替换。
"""

from __future__ import annotations

from dataclasses import dataclass

from exhibition_agent.contract.envelope import DataClassification, EgressDecision


@dataclass(frozen=True)
class ModelDecision:
    """Model Router 决策结果。"""

    model: str
    egress_decision: EgressDecision
    cost: float
    reason: str = ""


_STUB_DECISION = ModelDecision(
    model="stub-private-qwen",
    egress_decision=EgressDecision.ALLOW,
    cost=0.0,
    reason="Model Router 桩：不接真实模型",
)


def route_model(
    classification: DataClassification,
    *,
    task_type: str = "read_only_query",
) -> ModelDecision:
    """模型路由桩。

    生产实现依据「分级 + 企业出域策略」选择模型（Small / Private-Qwen / Private-DeepSeek / Cloud）。
    本桩：CONFIDENTIAL/PII/FINANCIAL → 拒绝出域（桩不处理敏感数据）；
    其余 → ALLOW + stub 模型 + 零成本。
    """
    if classification in (DataClassification.CONFIDENTIAL, DataClassification.PII, DataClassification.FINANCIAL):
        return ModelDecision(
            model="denied",
            egress_decision=EgressDecision.DENY,
            cost=0.0,
            reason=f"出域策略拒绝：classification={classification.value}",
        )
    return _STUB_DECISION
