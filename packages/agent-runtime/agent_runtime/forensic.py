"""Execution Forensic / Reproducibility（V3-9）。

现状（v3 之前）：``TrajectoryRecord`` 记录 execution_id / plan / steps / result /
error / latency / tokens / cost / snapshot，能检测"Step 3 发生 divergence"，
但不能回答"是模型变 / prompt 变 / Skill schema 变 / 数据变 / 外部 API 结果变 / Policy 变"。

本模块补上版本指纹：
- ``ForensicContext``：一次执行的版本指纹（model / prompt / skill / planner / policy 版本）；
- ``StepForensic``：单步版本指纹（per-step skill / tool / model 版本 + external receipt）；
- ``divergence_diagnosis``：对比两次执行的 forensic context，定位漂移源。

从"行为漂移检测"升级到"Execution forensic / reproducibility"。
与 Skill version / lifecycle（V3-10）联动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ForensicContext:
    """一次执行的版本指纹（reproducibility 追踪）。

    所有字段可选——未记录的维度不参与 divergence 诊断。
    """

    model: str | None = None  # 如 "gpt-4o"
    model_version: str | None = None  # 如 "2024-08-06"
    provider: str | None = None  # 如 "openai"
    prompt_version: str | None = None  # 如 "v2.3"
    skill_version: str | None = None  # 如 "exhibition-v1.2"
    input_schema_version: str | None = None  # 如 "v1"
    tool_schema_version: str | None = None  # 如 "v3"
    planner_version: str | None = None  # 如 "agentic-v2"
    policy_version: str | None = None  # 如 "rate-limit-v1.5"
    # 重要外部输入快照（hash / reference，非全文）
    external_inputs: dict[str, str] = field(default_factory=dict)  # source → hash/ref
    # 外部任务回执（证明外部系统确实执行了）
    external_task_receipts: dict[str, str] = field(default_factory=dict)  # task_id → receipt_hash
    # 副作用回执
    effect_receipts: dict[str, str] = field(default_factory=dict)  # effect_key → receipt_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_version": self.model_version,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "skill_version": self.skill_version,
            "input_schema_version": self.input_schema_version,
            "tool_schema_version": self.tool_schema_version,
            "planner_version": self.planner_version,
            "policy_version": self.policy_version,
            "external_inputs": self.external_inputs,
            "external_task_receipts": self.external_task_receipts,
            "effect_receipts": self.effect_receipts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ForensicContext:
        return cls(
            model=d.get("model"),
            model_version=d.get("model_version"),
            provider=d.get("provider"),
            prompt_version=d.get("prompt_version"),
            skill_version=d.get("skill_version"),
            input_schema_version=d.get("input_schema_version"),
            tool_schema_version=d.get("tool_schema_version"),
            planner_version=d.get("planner_version"),
            policy_version=d.get("policy_version"),
            external_inputs=d.get("external_inputs", {}),
            external_task_receipts=d.get("external_task_receipts", {}),
            effect_receipts=d.get("effect_receipts", {}),
        )


@dataclass
class StepForensic:
    """单步版本指纹（per-step skill / tool / model 版本 + external receipt）。"""

    skill_name: str | None = None
    skill_version: str | None = None
    tool_name: str | None = None
    tool_version: str | None = None
    model: str | None = None
    model_version: str | None = None
    # 外部 API 调用回执（如 HTTP response hash / job_id）
    external_call_receipt: str | None = None
    # 副作用回执
    effect_receipt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "model": self.model,
            "model_version": self.model_version,
            "external_call_receipt": self.external_call_receipt,
            "effect_receipt": self.effect_receipt,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepForensic:
        return cls(
            skill_name=d.get("skill_name"),
            skill_version=d.get("skill_version"),
            tool_name=d.get("tool_name"),
            tool_version=d.get("tool_version"),
            model=d.get("model"),
            model_version=d.get("model_version"),
            external_call_receipt=d.get("external_call_receipt"),
            effect_receipt=d.get("effect_receipt"),
        )


@dataclass
class DivergenceFinding:
    """单维度漂移发现。"""

    dimension: str  # "model" / "prompt_version" / "skill_version" / ...
    baseline_value: Any
    comparison_value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "baseline": self.baseline_value,
            "comparison": self.comparison_value,
        }


def divergence_diagnosis(
    baseline: ForensicContext,
    comparison: ForensicContext,
) -> list[DivergenceFinding]:
    """对比两次执行的 forensic context，定位漂移源。

    返回所有维度中 baseline ≠ comparison 的发现列表。
    空列表 = 两次执行的版本指纹完全一致（行为漂移非版本变更引起）。
    """
    findings: list[DivergenceFinding] = []
    scalar_fields = [
        "model", "model_version", "provider", "prompt_version",
        "skill_version", "input_schema_version", "tool_schema_version",
        "planner_version", "policy_version",
    ]
    for field_name in scalar_fields:
        base_val = getattr(baseline, field_name)
        comp_val = getattr(comparison, field_name)
        if base_val is not None and comp_val is not None and base_val != comp_val:
            findings.append(
                DivergenceFinding(field_name, base_val, comp_val)
            )

    # dict 字段：逐 key 对比
    for dict_field in ["external_inputs", "external_task_receipts", "effect_receipts"]:
        base_dict = getattr(baseline, dict_field)
        comp_dict = getattr(comparison, dict_field)
        for key in base_dict:
            if key in comp_dict and base_dict[key] != comp_dict[key]:
                findings.append(
                    DivergenceFinding(
                        f"{dict_field}.{key}",
                        base_dict[key],
                        comp_dict[key],
                    )
                )

    return findings


__all__ = [
    "ForensicContext",
    "StepForensic",
    "DivergenceFinding",
    "divergence_diagnosis",
]
