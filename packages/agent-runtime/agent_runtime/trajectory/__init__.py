"""Trajectory 持久化 + 重放（P3-1 / P3-2）：执行轨迹记录 + 存储后端 + Replay 比对。"""

from __future__ import annotations

from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep
from agent_runtime.trajectory.replay import (
    ReplayDivergence,
    ReplayRegistry,
    ReplayReport,
    build_replay_registry,
    replay_trajectory,
)
from agent_runtime.trajectory.store import (
    InMemoryTrajectoryStore,
    TrajectoryStore,
    _coerce_record,
)
from agent_runtime.trajectory.store_pg import PgTrajectoryStore

__all__ = [
    "TrajectoryRecord",
    "TrajectoryStep",
    "TrajectoryStore",
    "InMemoryTrajectoryStore",
    "PgTrajectoryStore",
    "_coerce_record",
    "ReplayDivergence",
    "ReplayRegistry",
    "ReplayReport",
    "build_replay_registry",
    "replay_trajectory",
]
