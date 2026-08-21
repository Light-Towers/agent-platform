"""Trajectory 持久化模型（P3-1）。

一条 ``TrajectoryRecord`` 对应一次 Planner 执行（一个 ``execution_id``），承载：
- 执行上下文关联：``execution_id`` / ``parent_execution_id`` / ``session_id`` / ``planner``；
- 决策产物 ``plan``（决策期结构化输出）；
- 逐步明细 ``steps``（skill / args / result / latency / tokens / error）；
- 累计 ``total_tokens`` / ``total_cost`` 与结构化 ``snapshot``。

模型层零第三方依赖（stdlib + dataclasses），存储后端见 ``store.py``。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrajectoryStep:
    """单次 Skill 调用明细：名称 / 入参 / 结果 / 耗时 / token / 错误。"""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    latency: float = 0.0
    tokens: int = 0
    # 调用序（同 execution 内从 0 递增），便于 replay 还原顺序
    index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "error": self.error,
            "latency": self.latency,
            "tokens": self.tokens,
            "index": self.index,
        }


@dataclass
class TrajectoryRecord:
    """一次执行的完整轨迹（可持久化 + 可查询）。"""

    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_execution_id: str | None = None
    session_id: str | None = None
    planner: str | None = None
    plan: dict[str, Any] = field(default_factory=dict)
    steps: list[TrajectoryStep] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "parent_execution_id": self.parent_execution_id,
            "session_id": self.session_id,
            "planner": self.planner,
            "plan": self.plan,
            "steps": [s.to_dict() for s in self.steps],
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "snapshot": self.snapshot,
            "created_at": self.created_at,
        }


__all__ = ["TrajectoryStep", "TrajectoryRecord"]
