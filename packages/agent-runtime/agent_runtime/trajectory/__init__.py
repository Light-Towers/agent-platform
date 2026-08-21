"""Trajectory 持久化（P3-1）：执行轨迹记录 + 存储后端。"""

from __future__ import annotations

from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep
from agent_runtime.trajectory.store import (
    InMemoryTrajectoryStore,
    TrajectoryStore,
    _coerce_record,
)

__all__ = [
    "TrajectoryRecord",
    "TrajectoryStep",
    "TrajectoryStore",
    "InMemoryTrajectoryStore",
    "_coerce_record",
]
