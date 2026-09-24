"""§17.5 Model Router — F02 落地版（对接 foundation/data_egress）。

Agent 不得自选模型，统一由 Model Router 决策。
路由输入：数据分级 + 出域决策 + 任务类型 + 模型能力 + 延迟 + 成本 + 企业配置。
出域策略未过 → 直接拒绝（EGRESS_DENIED），不得降级到云模型。

本模块是 exhibition-agent 平台侧入口（graph/nodes.py 调用），保留 ModelDecision
数据类与 route_model(classification, *, task_type) 签名向后兼容；内部委托
foundation.data_egress 完成实际分级/出域/路由/审计/脱敏链路。

完整链路（F02）：
  数据分级（DataClass 5 级）
  → 出域策略（EgressPolicy: enterprise_a / enterprise_b）
  → 模型路由（route_model: Small / Private / Cloud；deny → REJECT）
  → PII 脱敏（mask_pii，入模前调用）
  → LLM 调用（execute_llm，占位待 F2 决策）
  → 审计（record_egress_audit，100% 覆盖）
"""

from __future__ import annotations

from dataclasses import dataclass

from exhibition_agent.contract.envelope import DataClassification, EgressDecision
from exhibition_agent.foundation.data_egress import (
    DataClass,
    EgressPolicy,
)
from exhibition_agent.foundation.data_egress import (
    execute_llm as _egress_execute_llm,
)
from exhibition_agent.foundation.data_egress import (
    route_model as _egress_route_model,
)


@dataclass(frozen=True)
class ModelDecision:
    """Model Router 决策结果（平台侧消费，graph/nodes.py 用）。"""

    model: str
    egress_decision: EgressDecision
    cost: float
    reason: str = ""


# DataClassification (envelope) ↔ DataClass (data_egress) 同名同值，按 value 映射
_DC_TO_DATACLASS = {dc.value: dc for dc in DataClass}

# data_egress.EgressDecision (allow/mask_then_allow/deny) → envelope.EgressDecision (ALLOW/MASKED/DENY)
_EGRESS_TO_ENVELOPE = {
    "allow": EgressDecision.ALLOW,
    "mask_then_allow": EgressDecision.MASKED,
    "deny": EgressDecision.DENY,
}

# model_category → model 标识（占位，待 F2 决策后替换真实模型 ID）
_MODEL_BY_CATEGORY = {
    "Small": "small-local-qwen",
    "Private": "private-qwen",
    "Cloud": "cloud-qwen",
    "deny": "denied",
}


def _classify_to_dataclass(classification: DataClassification) -> DataClass:
    """envelope.DataClassification → data_egress.DataClass（按 value 映射）。"""
    return _DC_TO_DATACLASS[classification.value]


def route_model(
    classification: DataClassification,
    *,
    task_type: str = "read_only_query",
    policy: EgressPolicy | None = None,
) -> ModelDecision:
    """模型路由（平台侧入口，graph/nodes.py 调用）。

    内部委托 foundation.data_egress.route_model：
      - 出域未过 → egress_decision=DENY（不降级到云模型）
      - 轻量前置任务（routing/intent_classification/query_rewrite/guardrail）→ Small
      - 允许出域 → Cloud
      - 其余 → Private

    policy 默认企业 A（enterprise_a）。
    """
    if policy is None:
        policy = EgressPolicy("enterprise_a")

    data_class = _classify_to_dataclass(classification)
    raw = _egress_route_model(data_class, policy, task_type=task_type)

    model_category = raw["model_category"]
    action = raw["action"]
    egress_decision = _EGRESS_TO_ENVELOPE.get(action, EgressDecision.DENY)

    return ModelDecision(
        model=_MODEL_BY_CATEGORY.get(model_category, "unknown"),
        egress_decision=egress_decision,
        cost=0.0,
        reason=raw.get("reason", ""),
    )


def execute_llm(model_category: str, prompt: str, **kwargs) -> dict:
    """LLM 调用实体（桥接 foundation.data_egress.execute_llm）。

    route_model 返回 model_category 后，由调用方按 category 分发到不同 LLM。
    当前为占位（标 TODO 待 F2 决策后接入真实 LLM 连接）。
    调用方应在传入 prompt 前调用 mask_pii 脱敏（RD7）。
    """
    return _egress_execute_llm(model_category, prompt, **kwargs)
