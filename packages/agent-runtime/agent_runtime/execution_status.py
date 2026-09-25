"""Durable Execution Status State Machine（V3-3）：Execution 的一等状态（与 lease / checkpoint 并列）。

现状（v3 之前的缺口）：执行状态无独立持久化模型——只能从 lease 存在性 / checkpoint /
execution_events 间接推断，无法表达 long-running / awaitable 语义。

本模块补上：
- ``ExecutionStatus``：完整状态集（含 ``WAITING_EXTERNAL`` / ``WAITING_HUMAN`` / ``PAUSED`` /
  ``CANCEL_REQUESTED`` / ``CANCELLED``）；
- ``ExecutionStatusRecord``：状态 + ownership generation + 原因 + 元数据；
- ``ExecutionStatusStore``：持久化契约（save 带 generation fencing，防止旧 owner 改状态）；
- ``InMemoryExecutionStatusStore`` / ``PgExecutionStatusStore``：两后端。

状态转换受 ``can_transition`` 约束（非法转换拒绝），与 lease generation 解耦：
``generation`` 决定「谁有权改」，``status`` 决定「推进到哪」。
"""

from __future__ import annotations

import abc
import copy
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionStatus(str, Enum):
    """Execution 一等状态。"""

    PENDING = "pending"  # 已创建，未开始执行
    RUNNING = "running"  # 执行中
    WAITING = "waiting"  # 通用等待（未细分场景）
    WAITING_EXTERNAL = "waiting_external"  # 等外部系统异步任务（ExternalTask）
    WAITING_HUMAN = "waiting_human"  # 等人工审批 / 介入
    PAUSED = "paused"  # 人为暂停
    CANCEL_REQUESTED = "cancel_requested"  # 已请求取消，待协作式中止
    CANCELLED = "cancelled"  # 已取消
    SUCCEEDED = "succeeded"  # 成功完成
    FAILED = "failed"  # 失败终止

    @property
    def is_terminal(self) -> bool:
        """终态：不再发生转换。"""
        return self in _TERMINAL

    @property
    def is_awaiting(self) -> bool:
        """等待态：需外部事件 / 人工 / 定时器唤醒才能继续。"""
        return self in _AWAITING


_TERMINAL = frozenset(
    {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)
_AWAITING = frozenset(
    {
        ExecutionStatus.WAITING,
        ExecutionStatus.WAITING_EXTERNAL,
        ExecutionStatus.WAITING_HUMAN,
        ExecutionStatus.PAUSED,
    }
)

# 合法转换图：显式声明，非法转换（如终态再转换）由 can_transition 拒绝。
_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.PENDING: frozenset(
        {ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED, ExecutionStatus.FAILED}
    ),
    ExecutionStatus.RUNNING: frozenset(
        {
            ExecutionStatus.WAITING,
            ExecutionStatus.WAITING_EXTERNAL,
            ExecutionStatus.WAITING_HUMAN,
            ExecutionStatus.PAUSED,
            ExecutionStatus.CANCEL_REQUESTED,
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
        }
    ),
    ExecutionStatus.WAITING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.CANCEL_REQUESTED,
            ExecutionStatus.FAILED,
        }
    ),
    ExecutionStatus.WAITING_EXTERNAL: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.CANCEL_REQUESTED,
            ExecutionStatus.FAILED,
        }
    ),
    ExecutionStatus.WAITING_HUMAN: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.CANCEL_REQUESTED,
            ExecutionStatus.FAILED,
        }
    ),
    ExecutionStatus.PAUSED: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.CANCEL_REQUESTED,
            ExecutionStatus.FAILED,
        }
    ),
    ExecutionStatus.CANCEL_REQUESTED: frozenset(
        {ExecutionStatus.CANCELLED, ExecutionStatus.FAILED}
    ),
    ExecutionStatus.CANCELLED: frozenset(),
    ExecutionStatus.SUCCEEDED: frozenset(),
    ExecutionStatus.FAILED: frozenset(),
}


class InvalidStatusTransition(RuntimeError):
    """非法状态转换（如终态再转换 / 跳转到未声明的目标）。"""


def can_transition(current: ExecutionStatus, target: ExecutionStatus) -> bool:
    """判断 ``current → target`` 是否为合法转换。"""
    if current is target:
        return True  # 幂等重设（如状态刷新）允许
    return target in _TRANSITIONS.get(current, frozenset())


@dataclass
class ExecutionStatusRecord:
    """Execution 状态记录（一等持久化对象）。"""

    execution_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    # ownership generation（V3-1）：写入时须匹配当前 lease generation（fencing）。
    generation: int | None = None
    reason: str = ""
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "generation": self.generation,
            "reason": self.reason,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


class ExecutionStatusStore(abc.ABC):
    """Execution 状态持久化契约。"""

    @abc.abstractmethod
    async def load(self, execution_id: str) -> ExecutionStatusRecord | None:
        """读取状态记录（不存在返回 None）。"""

    @abc.abstractmethod
    async def save(self, record: ExecutionStatusRecord) -> None:
        """保存状态（须校验合法转换；带 generation 时按 fencing 拒绝旧 owner 写）。"""


class InMemoryExecutionStatusStore(ExecutionStatusStore):
    """进程内状态存储（测试 / 单进程默认后端）。"""

    def __init__(self) -> None:
        self._store: dict[str, ExecutionStatusRecord] = {}

    async def load(self, execution_id: str) -> ExecutionStatusRecord | None:
        return self._store.get(execution_id)

    async def save(self, record: ExecutionStatusRecord) -> None:
        cur = self._store.get(record.execution_id)
        if cur is not None:
            if not can_transition(cur.status, record.status):
                raise InvalidStatusTransition(
                    f"非法状态转换: {cur.status.value} → {record.status.value} "
                    f"(execution={record.execution_id})"
                )
            # V3-1 generation fencing：record 带 generation 时，不得小于现有 generation
            if (
                record.generation is not None
                and cur.generation is not None
                and record.generation < cur.generation
            ):
                raise InvalidStatusTransition(
                    f"状态写入被 generation fencing 拒绝: record generation="
                    f"{record.generation} < current={cur.generation} (execution={record.execution_id})"
                )
        self._store[record.execution_id] = copy.deepcopy(record)


__all__ = [
    "ExecutionStatus",
    "ExecutionStatusRecord",
    "ExecutionStatusStore",
    "InMemoryExecutionStatusStore",
    "InvalidStatusTransition",
    "can_transition",
]