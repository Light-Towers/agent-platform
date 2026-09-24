"""Human Task / Approval（V3 补-1 应用层）。

.. warning::
   **STATUS: NOT WIRED** – 本模块有完整实现与单测，但 applications/ 层零调用。
   属「设计就绪、待集成」状态，不得视为已上线能力。(P1-7 审计披露 2026-09-24)

V3-3 的 ``AwaitableTask`` 已支持 ``AwaitableKind.HUMAN``，``ExecutionStatus`` 已支持
``WAITING_HUMAN``。本模块是人工审批 / 介入的**应用层**：

- ``HumanTask``：人工审批任务（prompt / options / deadline / approver）；
- ``HumanTaskStore``：基于 ``AwaitableTaskStore`` 的人工任务持久化；
- ``HumanTaskResolver``：审批结果注入 + 执行恢复。

流程：
```
Execution 到达需人工确认节点
  ↓
HumanTaskStore.create → AwaitableTask(HUMAN, PENDING)
  ↓
ExecutionStatus → WAITING_HUMAN（释放 Worker）
  ↓
人工审批 → HumanTaskResolver.resolve(task_id, decision)
  ↓
AwaitableTask → COMPLETED + resume_payload
  ↓
ExecutionStatus → RUNNING（重新调度）
```
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    AwaitableTaskStore,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    ExecutionStatusStore,
)

logger = logging.getLogger(__name__)


class HumanTaskDecision(str, Enum):
    """人工审批决策。"""

    APPROVED = "approved"  # 批准
    REJECTED = "rejected"  # 驳回
    DEFERRED = "deferred"  # 延期（需后续再审）


@dataclass
class HumanTask:
    """人工审批任务（AwaitableTask 的应用层封装）。"""

    execution_id: str
    step_id: str
    prompt: str  # 向审批人展示的说明
    options: list[str] = field(default_factory=lambda: ["approve", "reject"])  # 可选项
    deadline: float | None = None  # 审批截止时间
    approver: str | None = None  # 指定审批人
    context: dict[str, Any] = field(default_factory=dict)  # 审批上下文（如变更内容摘要）
    # 关联的 AwaitableTask
    task: AwaitableTask | None = None

    @property
    def task_id(self) -> str | None:
        return self.task.task_id if self.task else None

    @property
    def state(self) -> AwaitableState | None:
        return self.task.state if self.task else None


class HumanTaskStore:
    """人工任务持久化（基于 AwaitableTaskStore）。"""

    def __init__(self, awaitable_store: AwaitableTaskStore) -> None:
        self._store = awaitable_store

    async def create(self, task: HumanTask) -> AwaitableTask:
        """创建人工审批任务（PENDING）。"""
        awaitable = AwaitableTask(
            execution_id=task.execution_id,
            step_id=task.step_id,
            kind=AwaitableKind.HUMAN,
            provider="human",
            state=AwaitableState.PENDING,
            deadline=task.deadline,
            metadata={
                "prompt": task.prompt,
                "options": task.options,
                "approver": task.approver,
                "context": task.context,
            },
        )
        await self._store.save(awaitable)
        task.task = awaitable
        logger.info(
            "human task created execution=%s step=%s task=%s",
            task.execution_id, task.step_id, awaitable.task_id,
        )
        return awaitable

    async def submit(self, task_id: str, approver: str) -> AwaitableTask:
        """提交审批（PENDING → SUBMITTED，记录审批人）。"""
        task = await self._store.load(task_id)
        if task is None:
            raise ValueError(f"人工任务不存在: {task_id}")

        task.state = AwaitableState.SUBMITTED
        task.provider_task_id = approver
        task.submitted_at = time.time()
        task.metadata["submitted_by"] = approver
        await self._store.save(task)
        return task

    async def resolve(
        self,
        task_id: str,
        decision: HumanTaskDecision,
        approver: str,
        comment: str = "",
    ) -> AwaitableTask:
        """审批完成（SUBMITTED → COMPLETED），注入 resume_payload。"""
        task = await self._store.load(task_id)
        if task is None:
            raise ValueError(f"人工任务不存在: {task_id}")

        if task.state is AwaitableState.PENDING:
            task.state = AwaitableState.SUBMITTED
            task.provider_task_id = approver
            task.submitted_at = time.time()
            await self._store.save(task)

        task.state = AwaitableState.COMPLETED
        task.completion_receipt = {
            "decision": decision.value,
            "approver": approver,
            "comment": comment,
            "resolved_at": time.time(),
        }
        task.completed_at = time.time()
        task.resume_payload = {
            "decision": decision.value,
            "comment": comment,
            "approver": approver,
        }
        await self._store.save(task)

        logger.info(
            "human task resolved task=%s decision=%s approver=%s",
            task_id, decision.value, approver,
        )
        return task

    async def reject(
        self,
        task_id: str,
        approver: str,
        reason: str = "",
    ) -> AwaitableTask:
        """审批驳回（→ FAILED）。"""
        task = await self._store.load(task_id)
        if task is None:
            raise ValueError(f"人工任务不存在: {task_id}")

        task.state = AwaitableState.FAILED
        task.completion_receipt = {
            "decision": "rejected",
            "approver": approver,
            "reason": reason,
            "resolved_at": time.time(),
        }
        task.completed_at = time.time()
        await self._store.save(task)

        logger.info("human task rejected task=%s approver=%s", task_id, approver)
        return task

    async def get(self, task_id: str) -> AwaitableTask | None:
        return await self._store.load(task_id)

    async def list_pending(self, execution_id: str) -> list[AwaitableTask]:
        """列出执行的所有未完成人工任务。"""
        tasks = await self._store.list_by_execution(execution_id)
        return [
            t for t in tasks
            if t.kind is AwaitableKind.HUMAN and not t.state.is_terminal
        ]


class HumanTaskResolver:
    """人工审批 resolver：审批结果注入 + 执行恢复。"""

    def __init__(
        self,
        human_store: HumanTaskStore,
        status_store: ExecutionStatusStore | None = None,
    ) -> None:
        self._human_store = human_store
        self._status_store = status_store

    async def resolve_and_resume(
        self,
        task_id: str,
        decision: HumanTaskDecision,
        approver: str,
        comment: str = "",
    ) -> AwaitableTask:
        """审批完成 + 恢复执行（WAITING_HUMAN → RUNNING）。"""
        task = await self._human_store.resolve(task_id, decision, approver, comment)

        if self._status_store is not None and decision is HumanTaskDecision.APPROVED:
            try:
                current = await self._status_store.load(task.execution_id)
                if current is not None and current.status is ExecutionStatus.WAITING_HUMAN:
                    await self._status_store.save(
                        ExecutionStatusRecord(
                            task.execution_id,
                            ExecutionStatus.RUNNING,
                            generation=current.generation,
                            reason=f"human_approved:{task_id}",
                        )
                    )
                    logger.info(
                        "execution resumed after human approval execution=%s",
                        task.execution_id,
                    )
            except Exception:
                logger.warning(
                    "resume after human approval failed execution=%s",
                    task.execution_id,
                    exc_info=True,
                )

        return task

    async def reject_and_fail(
        self,
        task_id: str,
        approver: str,
        reason: str = "",
    ) -> AwaitableTask:
        """审批驳回 + 标记执行失败。"""
        task = await self._human_store.reject(task_id, approver, reason)

        if self._status_store is not None:
            try:
                current = await self._status_store.load(task.execution_id)
                if current is not None and not current.status.is_terminal:
                    await self._status_store.save(
                        ExecutionStatusRecord(
                            task.execution_id,
                            ExecutionStatus.FAILED,
                            generation=current.generation,
                            reason=f"human_rejected:{task_id}",
                        )
                    )
            except Exception:
                logger.warning(
                    "mark failed after human rejection failed execution=%s",
                    task.execution_id,
                    exc_info=True,
                )

        return task


__all__ = [
    "HumanTaskDecision",
    "HumanTask",
    "HumanTaskStore",
    "HumanTaskResolver",
]
