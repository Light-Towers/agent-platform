"""Awaitable Task（V3-3）：跨外部系统 / 人工 / 定时器 / 回调的 durable execution。

现状（v3 之前的缺口）：Durable Execution 只覆盖「Agent crash → checkpoint → resume」，
不覆盖「外部任务异步进行时 Agent 不应一直占 worker」；恢复时不知道外部任务实际状态，
只能盲目重调 Tool。

本模块补上：
- ``AwaitableTask``：长时/可等待任务的统一持久化载体（External / Human / Timer / Callback）；
- ``AwaitableState``：状态机（PENDING → SUBMITTED → RUNNING → COMPLETED，异常 FAILED/TIMED_OUT/
  CANCELLED/UNKNOWN）；
- 回执（submission_receipt / completion_receipt / provider_task_id），供恢复时 query 外部状态；
- ``AwaitableTaskStore``：持久化契约（InMemory + PG）。

crash recovery 语义：
```
agent crash
  ↓
load AwaitableTask
  ↓
query external system（据 provider_task_id / submission_receipt）
  ↓
determine actual state → 更新
  ↓
continue 或 补偿
```
"""

from __future__ import annotations

import abc
import copy
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AwaitableKind(str, Enum):
    """可等待任务的类别（统一抽象）。"""

    EXTERNAL = "external"  # 外部系统异步任务（job_id / 异步 API / MCP 后端任务）
    HUMAN = "human"  # 人工审批 / 介入
    TIMER = "timer"  # 定时唤醒
    CALLBACK = "callback"  # 回调 / Webhook


class AwaitableState(str, Enum):
    """可等待任务状态机。"""

    PENDING = "pending"  # 已创建，未提交
    SUBMITTED = "submitted"  # 已提交外部，待回执
    RUNNING = "running"  # 外部执行中
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"  # 失败
    TIMED_OUT = "timed_out"  # 超时
    CANCELLED = "cancelled"  # 已取消
    UNKNOWN = "unknown"  # 状态不确定（crash 后无回执，需 query 外部系统确定）

    @property
    def is_terminal(self) -> bool:
        return self in _TASK_TERMINAL

    @property
    def needs_resolution(self) -> bool:
        """需查询外部系统确定实际状态（恢复路径）。"""
        return self in {AwaitableState.UNKNOWN, AwaitableState.SUBMITTED, AwaitableState.RUNNING}


_TASK_TERMINAL = frozenset(
    {
        AwaitableState.COMPLETED,
        AwaitableState.FAILED,
        AwaitableState.TIMED_OUT,
        AwaitableState.CANCELLED,
    }
)

_TASK_TRANSITIONS: dict[AwaitableState, frozenset[AwaitableState]] = {
    AwaitableState.PENDING: frozenset(
        {AwaitableState.SUBMITTED, AwaitableState.CANCELLED, AwaitableState.FAILED}
    ),
    AwaitableState.SUBMITTED: frozenset(
        {
            AwaitableState.RUNNING,
            AwaitableState.COMPLETED,
            AwaitableState.FAILED,
            AwaitableState.TIMED_OUT,
            AwaitableState.CANCELLED,
            AwaitableState.UNKNOWN,
        }
    ),
    AwaitableState.RUNNING: frozenset(
        {
            AwaitableState.COMPLETED,
            AwaitableState.FAILED,
            AwaitableState.TIMED_OUT,
            AwaitableState.CANCELLED,
            AwaitableState.UNKNOWN,
        }
    ),
    # UNKNOWN 经 query 外部系统后收敛到确定态（恢复路径）
    AwaitableState.UNKNOWN: frozenset(
        {
            AwaitableState.RUNNING,
            AwaitableState.COMPLETED,
            AwaitableState.FAILED,
            AwaitableState.TIMED_OUT,
            AwaitableState.CANCELLED,
        }
    ),
    AwaitableState.COMPLETED: frozenset(),
    AwaitableState.FAILED: frozenset(),
    AwaitableState.TIMED_OUT: frozenset(),
    AwaitableState.CANCELLED: frozenset(),
}


class InvalidTaskTransition(RuntimeError):
    """非法任务状态转换。"""


def can_transition(current: AwaitableState, target: AwaitableState) -> bool:
    """判断 ``current → target`` 是否为合法任务状态转换。"""
    if current is target:
        return True
    return target in _TASK_TRANSITIONS.get(current, frozenset())


@dataclass
class AwaitableTask:
    """长时 / 可等待任务的统一持久化载体。"""

    execution_id: str
    step_id: str
    kind: AwaitableKind
    provider: str  # 外部 provider 名（或 "human" / "timer" / "callback"）
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: AwaitableState = AwaitableState.PENDING
    # 外部系统任务 id（EXTERNAL 的 job_id / HUMAN 的 approval_id / TIMER 的 timer_id）
    provider_task_id: str | None = None
    # 回执：提交回执（证明已提交）/ 完成回执（证明已落地）——恢复时据此 query 外部状态
    submission_receipt: dict[str, Any] | None = None
    completion_receipt: dict[str, Any] | None = None
    submitted_at: float | None = None
    completed_at: float | None = None
    deadline: float | None = None
    # 唤醒时注入执行的数据（如人工审批结果、外部任务产出）
    resume_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "kind": self.kind.value,
            "provider": self.provider,
            "state": self.state.value,
            "provider_task_id": self.provider_task_id,
            "submission_receipt": self.submission_receipt,
            "completion_receipt": self.completion_receipt,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "deadline": self.deadline,
            "resume_payload": self.resume_payload,
            "metadata": self.metadata,
            "updated_at": self.updated_at,
        }


class AwaitableTaskStore(abc.ABC):
    """可等待任务持久化契约。"""

    @abc.abstractmethod
    async def save(self, task: AwaitableTask) -> None:
        """保存（新建/覆盖）；须校验合法状态转换。"""

    @abc.abstractmethod
    async def load(self, task_id: str) -> AwaitableTask | None:
        """按 task_id 读取。"""

    @abc.abstractmethod
    async def list_by_execution(self, execution_id: str) -> list[AwaitableTask]:
        """列出某 execution 下所有可等待任务。"""

    @abc.abstractmethod
    async def list_unresolved(self) -> list[AwaitableTask]:
        """列出所有未收敛（非终态）任务——供 reaper / resume 扫描。"""


class InMemoryAwaitableTaskStore(AwaitableTaskStore):
    """进程内可等待任务存储（测试 / 单进程默认后端）。"""

    def __init__(self) -> None:
        self._store: dict[str, AwaitableTask] = {}

    async def save(self, task: AwaitableTask) -> None:
        cur = self._store.get(task.task_id)
        if cur is not None and not can_transition(cur.state, task.state):
            raise InvalidTaskTransition(
                f"非法任务状态转换: {cur.state.value} → {task.state.value} (task={task.task_id})"
            )
        task.updated_at = time.time()
        # 存副本：与调用方对象解耦，避免调用方后续修改同一对象绕过状态转换校验
        self._store[task.task_id] = copy.deepcopy(task)

    async def load(self, task_id: str) -> AwaitableTask | None:
        return self._store.get(task_id)

    async def list_by_execution(self, execution_id: str) -> list[AwaitableTask]:
        return [t for t in self._store.values() if t.execution_id == execution_id]

    async def list_unresolved(self) -> list[AwaitableTask]:
        return [t for t in self._store.values() if not t.state.is_terminal]


__all__ = [
    "AwaitableKind",
    "AwaitableState",
    "AwaitableTask",
    "AwaitableTaskStore",
    "InMemoryAwaitableTaskStore",
    "InvalidTaskTransition",
    "can_transition",
]