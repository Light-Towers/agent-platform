"""Execution Lifecycle：显式控制 Agent Execution 的生命周期，而非穷举业务任务。

核心架构原则：
- 业务任务可以是动态的（LLM plan / re-plan / tool loop）；
- Runtime 不要求预先知道所有业务任务；
- Runtime 显式约束的是 execution lifecycle：准入、规划、执行、等待、checkpoint、
  重规划、恢复、完成/失败/取消；
- Agent 的每一次实际动作仍必须经过统一 Runtime / SkillRegistry 边界。

因此本状态机不是「把所有 Agent 任务写死」，而是给动态 Agent 提供一个确定性的
execution boundary。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any


class ExecutionState(StrEnum):
    CREATED = "created"
    ADMITTED = "admitted"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    CHECKPOINTED = "checkpointed"
    REPLANNING = "replanning"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidExecutionTransition(RuntimeError):
    """尝试越过 Runtime 定义的 execution lifecycle 边界。"""


_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.CREATED: frozenset({ExecutionState.ADMITTED, ExecutionState.CANCELLED}),
    ExecutionState.ADMITTED: frozenset({ExecutionState.PLANNING, ExecutionState.FAILED, ExecutionState.CANCELLED}),
    ExecutionState.PLANNING: frozenset({ExecutionState.RUNNING, ExecutionState.FAILED, ExecutionState.CANCELLED}),
    ExecutionState.RUNNING: frozenset({
        ExecutionState.WAITING,
        ExecutionState.CHECKPOINTED,
        ExecutionState.REPLANNING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    }),
    ExecutionState.WAITING: frozenset({ExecutionState.RUNNING, ExecutionState.FAILED, ExecutionState.CANCELLED}),
    ExecutionState.CHECKPOINTED: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.REPLANNING,
        ExecutionState.RECOVERING,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    }),
    ExecutionState.REPLANNING: frozenset({ExecutionState.PLANNING, ExecutionState.FAILED, ExecutionState.CANCELLED}),
    ExecutionState.RECOVERING: frozenset({ExecutionState.RUNNING, ExecutionState.PLANNING, ExecutionState.FAILED, ExecutionState.CANCELLED}),
    ExecutionState.COMPLETED: frozenset(),
    ExecutionState.FAILED: frozenset({ExecutionState.RECOVERING, ExecutionState.PLANNING, ExecutionState.CANCELLED}),
    ExecutionState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class ExecutionTransition:
    from_state: ExecutionState
    to_state: ExecutionState
    reason: str = ""
    at_monotonic: float = field(default_factory=monotonic)


@dataclass
class ExecutionLifecycle:
    """单次 execution 的显式生命周期状态机。

    ``state`` 描述 Runtime 如何管理一次执行；它不描述 LLM 具体要完成什么任务。
    业务计划可以随时变化，但必须落在这里定义的生命周期边界内。
    """

    state: ExecutionState = ExecutionState.CREATED
    history: list[ExecutionTransition] = field(default_factory=list)

    def transition(self, to_state: ExecutionState, *, reason: str = "") -> ExecutionTransition:
        allowed = _TRANSITIONS[self.state]
        if to_state not in allowed:
            raise InvalidExecutionTransition(
                f"非法 execution 状态迁移: {self.state} -> {to_state}"
                + (f" ({reason})" if reason else "")
            )
        event = ExecutionTransition(self.state, to_state, reason=reason)
        self.history.append(event)
        self.state = to_state
        return event

    def can_transition(self, to_state: ExecutionState) -> bool:
        return to_state in _TRANSITIONS[self.state]

    @property
    def terminal(self) -> bool:
        return self.state in {
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
        }

    def snapshot(self) -> dict[str, Any]:
        """返回可进入 checkpoint / trace 的稳定快照。"""
        return {
            "state": self.state.value,
            "history": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "reason": t.reason,
                    "at_monotonic": t.at_monotonic,
                }
                for t in self.history
            ],
        }


__all__ = [
    "ExecutionLifecycle",
    "ExecutionState",
    "ExecutionTransition",
    "InvalidExecutionTransition",
]
