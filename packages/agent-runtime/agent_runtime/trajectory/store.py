"""Trajectory 存储后端（P3-1）。

- ``TrajectoryStore``：持久化契约（``save`` / ``get`` / ``list_by_session``）。
- ``InMemoryTrajectoryStore``：进程内默认实现（测试 / 单进程部署够用）。
- PG 后端为可选增强（依赖 ``agent_core`` 的 DB 连接），本模块不强制依赖，
  由宿主在装配期注入自定义实现即可；故此处只落「模型 + 内存实现 + 契约」。
"""

from __future__ import annotations

import abc
from collections import OrderedDict
from typing import Any

from agent_runtime.trajectory.models import TrajectoryRecord


class TrajectoryStore(abc.ABC):
    """轨迹持久化契约：按 execution_id 写入与查询。"""

    @abc.abstractmethod
    async def save(self, record: TrajectoryRecord) -> None:
        """持久化一条执行轨迹。"""

    @abc.abstractmethod
    async def get(self, execution_id: str) -> TrajectoryRecord | None:
        """按 execution_id 查询完整轨迹（不存在返回 None）。"""

    @abc.abstractmethod
    async def list_by_session(self, session_id: str) -> list[TrajectoryRecord]:
        """按 session_id 倒序列出该会话的全部执行轨迹。"""


class InMemoryTrajectoryStore(TrajectoryStore):
    """进程内轨迹存储（LRU 上限，避免长进程无限增长）。

    单进程部署与测试默认后端；多副本场景应注入 PG 实现（见 roadmap P4-1 双写）。
    """

    def __init__(self, max_size: int = 1024) -> None:
        self._max_size = max_size
        self._store: OrderedDict[str, TrajectoryRecord] = OrderedDict()

    async def save(self, record: TrajectoryRecord) -> None:
        self._store[record.execution_id] = record
        self._store.move_to_end(record.execution_id)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    async def get(self, execution_id: str) -> TrajectoryRecord | None:
        return self._store.get(execution_id)

    async def list_by_session(self, session_id: str) -> list[TrajectoryRecord]:
        return [
            r
            for r in reversed(self._store.values())
            if r.session_id == session_id
        ]


def _coerce_record(data: dict[str, Any]) -> TrajectoryRecord:
    """dict → TrajectoryRecord（供 PG 等外部后端反序列化复用）。"""
    from agent_runtime.trajectory.models import TrajectoryStep

    steps = [
        TrajectoryStep(
            name=s["name"],
            args=s.get("args", {}),
            result=s.get("result"),
            error=s.get("error"),
            latency=s.get("latency", 0.0),
            tokens=s.get("tokens", 0),
            index=s.get("index", 0),
        )
        for s in data.get("steps", [])
    ]
    return TrajectoryRecord(
        execution_id=data["execution_id"],
        parent_execution_id=data.get("parent_execution_id"),
        session_id=data.get("session_id"),
        planner=data.get("planner"),
        plan=data.get("plan", {}),
        steps=steps,
        total_tokens=data.get("total_tokens", 0),
        total_cost=data.get("total_cost", 0.0),
        snapshot=data.get("snapshot", {}),
        created_at=data.get("created_at", 0.0),
    )


__all__ = ["TrajectoryStore", "InMemoryTrajectoryStore", "_coerce_record"]
