"""ContextValidator（Context Governance）：跨来源一致性校验。

召回的 Memory 可能与当前 State 不一致——例如 Memory 记录"用户偏好 A"，
但 State 显示用户已切换到 B。把不一致的 Memory 降权或剔除，避免 LLM 基于过期/
冲突信息做决策。

三类校验：
- **stale**：Memory 的 timestamp 比 State 的更新时间旧太多（超过 ``stale_threshold`` 秒），
  降权但不剔除（旧信息可能仍有参考价值）；
- **conflict**：Memory 的 metadata 中某个 key 与 State 中同名 key 值不同，
  按冲突严重度降权或剔除；
- **invalid**：Memory 的 content 引用了 State 中不存在的实体（通过 ``entity_keys``
  配置的 key 列表检查），直接剔除。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """单条校验问题。"""

    memory_index: int
    issue: str  # "stale" | "conflict" | "invalid"
    detail: str
    severity: float  # 0-1，越高越严重；>= drop_threshold 时剔除
    action: str = "downgrade"  # "downgrade" | "drop" | "keep"


@dataclass
class ValidationReport:
    """校验报告。"""

    issues: list[ValidationIssue] = field(default_factory=list)
    dropped_indices: list[int] = field(default_factory=list)
    downgrade_factors: dict[int, float] = field(default_factory=dict)  # index → 降权因子(0-1)

    @property
    def has_critical(self) -> bool:
        return any(i.action == "drop" for i in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [
                {
                    "memory_index": i.memory_index,
                    "issue": i.issue,
                    "detail": i.detail,
                    "severity": i.severity,
                    "action": i.action,
                }
                for i in self.issues
            ],
            "dropped_indices": list(self.dropped_indices),
            "downgrade_factors": dict(self.downgrade_factors),
        }


class ContextValidator:
    """跨来源一致性校验：召回 Memory vs 当前 State。

    用法::

        validator = ContextValidator()
        report = validator.validate(memories, state=state_snapshot)
        filtered = validator.apply(memories, report)

    ``state`` 是 ``AgentContext.snapshot()`` 的输出（含 task / execution 子 dict），
    也可传入任意扁平 dict。校验规则按 key 匹配，不要求结构完全一致。
    """

    def __init__(
        self,
        *,
        stale_threshold: float = 3600.0,  # 1h：Memory 比 State 旧超过此值视为 stale
        drop_threshold: float = 0.8,  # severity >= 此值时剔除
        conflict_keys: tuple[str, ...] = (
            "user_preference",
            "current_step",
            "task_status",
            "active_plan",
        ),
        entity_keys: tuple[str, ...] = (
            "execution_id",
            "task_id",
        ),
    ) -> None:
        self.stale_threshold = stale_threshold
        self.drop_threshold = drop_threshold
        self.conflict_keys = conflict_keys
        self.entity_keys = entity_keys

    def validate(
        self,
        memories: list[Any],  # list[MemoryRecallResult] 或含 metadata 的 dict
        state: dict[str, Any] | None = None,
        *,
        now: float | None = None,
    ) -> ValidationReport:
        """校验一批 Memory 与 State 的一致性，返回 ValidationReport。"""
        report = ValidationReport()
        if not state:
            return report

        import time

        current_time = now if now is not None else time.time()
        state_flat = _flatten_state(state)
        state_timestamp = float(state_flat.get("timestamp", current_time))

        for idx, mem in enumerate(memories):
            meta = _get_metadata(mem)
            mem_timestamp = float(meta.get("timestamp", 0.0))

            # 1. stale 检查
            if mem_timestamp > 0 and state_timestamp > 0:
                age_diff = state_timestamp - mem_timestamp
                if age_diff > self.stale_threshold:
                    severity = min(
                        age_diff / (self.stale_threshold * 4), 1.0
                    ) * 0.5  # stale 最多 severity 0.5
                    issue = ValidationIssue(
                        memory_index=idx,
                        issue="stale",
                        detail=f"memory age {age_diff:.0f}s > threshold {self.stale_threshold:.0f}s",
                        severity=severity,
                        action="downgrade",
                    )
                    report.issues.append(issue)
                    report.downgrade_factors[idx] = 1.0 - severity

            # 2. conflict 检查
            for key in self.conflict_keys:
                if key not in state_flat or key not in meta:
                    continue
                state_val = state_flat[key]
                mem_val = meta[key]
                if _values_conflict(state_val, mem_val):
                    severity = 0.9  # conflict 默认 0.9（>= drop_threshold → drop）
                    action = "drop" if severity >= self.drop_threshold else "downgrade"
                    issue = ValidationIssue(
                        memory_index=idx,
                        issue="conflict",
                        detail=f"key '{key}': state={state_val!r} vs memory={mem_val!r}",
                        severity=severity,
                        action=action,
                    )
                    report.issues.append(issue)
                    if action == "drop":
                        report.dropped_indices.append(idx)
                    else:
                        existing = report.downgrade_factors.get(idx, 1.0)
                        report.downgrade_factors[idx] = min(existing, 1.0 - severity)

            # 3. invalid 检查：Memory 引用了 State 中不存在的实体
            for key in self.entity_keys:
                if key not in meta:
                    continue
                mem_entity = meta[key]
                if key in state_flat:
                    state_entity = state_flat[key]
                    if _values_conflict(state_entity, mem_entity):
                        issue = ValidationIssue(
                            memory_index=idx,
                            issue="invalid",
                            detail=f"entity '{key}': memory references {mem_entity!r}, state has {state_entity!r}",
                            severity=1.0,
                            action="drop",
                        )
                        report.issues.append(issue)
                        if idx not in report.dropped_indices:
                            report.dropped_indices.append(idx)

        return report

    def apply(
        self,
        memories: list[Any],
        report: ValidationReport,
    ) -> list[Any]:
        """根据校验报告过滤 + 降权 Memory 列表。"""
        dropped = set(report.dropped_indices)
        result: list[Any] = []
        for idx, mem in enumerate(memories):
            if idx in dropped:
                continue
            factor = report.downgrade_factors.get(idx)
            if factor is not None and factor < 1.0:
                mem = _apply_score_factor(mem, factor)
            result.append(mem)
        return result


def _flatten_state(state: dict[str, Any]) -> dict[str, Any]:
    """把嵌套 state dict 扁平化为一层 key→value（供 key 匹配校验）。"""
    flat: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, dict):
            for sub_key, sub_val in value.items():
                flat[sub_key] = sub_val
                flat[f"{key}.{sub_key}"] = sub_val
        else:
            flat[key] = value
    return flat


def _get_metadata(mem: Any) -> dict[str, Any]:
    """从 MemoryRecallResult 或 dict 提取 metadata。"""
    if hasattr(mem, "metadata"):
        return dict(mem.metadata or {})
    if isinstance(mem, dict):
        return dict(mem.get("metadata", {}))
    return {}


def _values_conflict(a: Any, b: Any) -> bool:
    """判断两个值是否冲突（类型归一化后不等）。"""
    if a is None or b is None:
        return False
    return str(a) != str(b)


def _apply_score_factor(mem: Any, factor: float) -> Any:
    """对 Memory 的 score 施加降权因子。"""
    if hasattr(mem, "score") and hasattr(mem, "metadata"):
        from dataclasses import replace

        new_score = getattr(mem, "score", 0.0) * factor
        return replace(mem, score=new_score)
    if isinstance(mem, dict):
        mem = dict(mem)
        mem["score"] = float(mem.get("score", 0.0)) * factor
        return mem
    return mem
