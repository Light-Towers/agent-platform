"""统一 Execution Boundary：把动态 Agent 与 Runtime 生命周期接起来。

该模块刻意不定义业务任务，也不要求预先生成完整 DAG。
Agent loop 可以动态 plan / act / re-plan；每次执行仍进入统一的
``PlannerRuntime.execution``，并由 ``ExecutionLifecycle`` 约束生命周期。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from agent_runtime.planner.execution_lifecycle import ExecutionLifecycle, ExecutionState
from agent_runtime.planner.protocol import PlannerRuntime


class ExecutionBoundary(AbstractAsyncContextManager["ExecutionBoundary"]):
    """动态 Agent / Graph 共用的 Runtime execution boundary。

    使用方式：

        async with ExecutionBoundary(runtime) as boundary:
            boundary.planning()
            boundary.running()
            ...  # Agent 可以动态产生任意合法 Skill plan
            boundary.replanning("证据不足")
            boundary.planning()
            boundary.running()
            boundary.complete()

    ``runtime.execution`` 仍负责 ownership / heartbeat / composition budget 等执行护栏；
    本类负责把这些执行活动映射到一个可审计的显式生命周期。
    """

    def __init__(
        self,
        runtime: PlannerRuntime,
        *,
        execution_id: str | None = None,
        validate_composition: bool = True,
    ) -> None:
        self.runtime = runtime
        self.execution_id = execution_id
        self.validate_composition = validate_composition
        self.lifecycle = ExecutionLifecycle()
        self._scope: Any = None

    async def __aenter__(self) -> "ExecutionBoundary":
        self.lifecycle.transition(ExecutionState.ADMITTED, reason="execution boundary accepted")
        self._scope = self.runtime.execution(
            validate_composition=self.validate_composition,
            execution_id=self.execution_id,
        )
        try:
            await self._scope.__aenter__()
        except Exception:
            self.lifecycle.transition(ExecutionState.FAILED, reason="runtime execution admission failed")
            self._scope = None
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        try:
            if exc is not None and not self.lifecycle.terminal:
                self.lifecycle.transition(ExecutionState.FAILED, reason=str(exc))
            elif not self.lifecycle.terminal:
                self.complete()
        finally:
            if self._scope is not None:
                await self._scope.__aexit__(exc_type, exc, tb)
                self._scope = None
        return None

    def planning(self, reason: str = "") -> None:
        self.lifecycle.transition(ExecutionState.PLANNING, reason=reason)

    def running(self, reason: str = "") -> None:
        self.lifecycle.transition(ExecutionState.RUNNING, reason=reason)

    def waiting(self, reason: str = "") -> None:
        self.lifecycle.transition(ExecutionState.WAITING, reason=reason)

    def checkpointed(self, reason: str = "") -> None:
        self.lifecycle.transition(ExecutionState.CHECKPOINTED, reason=reason)

    def replanning(self, reason: str = "") -> None:
        self.lifecycle.transition(ExecutionState.REPLANNING, reason=reason)

    def recovering(self, reason: str = "") -> None:
        self.lifecycle.transition(ExecutionState.RECOVERING, reason=reason)

    def complete(self, reason: str = "execution completed") -> None:
        self.lifecycle.transition(ExecutionState.COMPLETED, reason=reason)

    def fail(self, reason: str = "execution failed") -> None:
        self.lifecycle.transition(ExecutionState.FAILED, reason=reason)

    def cancel(self, reason: str = "execution cancelled") -> None:
        self.lifecycle.transition(ExecutionState.CANCELLED, reason=reason)

    @property
    def state(self) -> ExecutionState:
        return self.lifecycle.state

    def snapshot(self) -> dict[str, Any]:
        """用于 checkpoint / trace 的生命周期快照。"""
        return self.lifecycle.snapshot()


__all__ = ["ExecutionBoundary"]
