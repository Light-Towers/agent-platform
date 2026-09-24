"""Working Memory（四类 Memory 阶段 1A）：当前任务正在发生什么。

将 V3 已有的三套独立 Store（CheckpointStore + ExecutionStatusStore + AwaitableTaskStore）
统一抽象为 ``WorkingMemory`` 门面，提供执行态的完整快照与 save/load 操作。

与其他三类 Memory 的区别：
- Working：当前 execution 的实时状态（自动更新，任务结束不一定保留）
- Episodic：过去执行经历（需判断价值后沉淀）
- Semantic：业务事实/知识（结构化事实）
- Procedural：做事方法（Skill / Workflow）

存储后端：
- Checkpoint → PG execution_checkpoints（已完成节点结果）
- Status → PG execution_status（10 态状态机）
- Awaitable → PG awaitable_tasks（外部/人工/定时/回调任务）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.awaitable_task import AwaitableTask, AwaitableTaskStore
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    ExecutionStatusStore,
)
from agent_runtime.planner.durability import Checkpoint, CheckpointStore

logger = logging.getLogger(__name__)


@dataclass
class WorkingMemorySnapshot:
    """一次执行的 Working Memory 完整快照。"""

    execution_id: str
    status: ExecutionStatus | None = None
    status_generation: int | None = None
    checkpoint: Checkpoint | None = None
    awaitable_tasks: list[AwaitableTask] = field(default_factory=list)

    @property
    def completed_nodes(self) -> list[str]:
        """已完成节点 ID 列表。"""
        if self.checkpoint is None:
            return []
        return list(self.checkpoint.completed.keys())

    @property
    def is_running(self) -> bool:
        return self.status is ExecutionStatus.RUNNING

    @property
    def is_waiting(self) -> bool:
        """是否在等待（外部 / 人工 / 定时器）。"""
        return self.status in (
            ExecutionStatus.WAITING,
            ExecutionStatus.WAITING_EXTERNAL,
            ExecutionStatus.WAITING_HUMAN,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        )

    @property
    def pending_awaitables(self) -> list[AwaitableTask]:
        """未收敛的可等待任务。"""
        return [t for t in self.awaitable_tasks if not t.state.is_terminal]

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "status": self.status.value if self.status else None,
            "status_generation": self.status_generation,
            "completed_nodes": self.completed_nodes,
            "checkpoint_resumable": self.checkpoint.resumable if self.checkpoint else False,
            "checkpoint_generation": self.checkpoint.generation if self.checkpoint else None,
            "awaitable_count": len(self.awaitable_tasks),
            "pending_awaitable_count": len(self.pending_awaitables),
            "is_running": self.is_running,
            "is_waiting": self.is_waiting,
            "is_terminal": self.is_terminal,
        }


class WorkingMemory:
    """Working Memory 门面：组合 Checkpoint + Status + Awaitable。

    用法：
    ```
    wm = WorkingMemory(
        checkpoint_store=PgCheckpointStore(pool),
        status_store=PgExecutionStatusStore(pool),
        awaitable_store=PgAwaitableTaskStore(pool),
    )
    # 获取完整快照
    snap = await wm.snapshot("e123")
    # 保存执行态
    await wm.save_checkpoint(cp)
    await wm.save_status(ExecutionStatusRecord("e123", ExecutionStatus.RUNNING))
    # 加载用于 resume
    snap = await wm.load_for_resume("e123")
    ```
    """

    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
        status_store: ExecutionStatusStore | None = None,
        awaitable_store: AwaitableTaskStore | None = None,
    ) -> None:
        self._checkpoint = checkpoint_store
        self._status = status_store
        self._awaitable = awaitable_store

    async def snapshot(self, execution_id: str) -> WorkingMemorySnapshot:
        """获取执行的完整 Working Memory 快照。"""
        snap = WorkingMemorySnapshot(execution_id=execution_id)

        if self._status is not None:
            try:
                rec = await self._status.load(execution_id)
                if rec is not None:
                    snap.status = rec.status
                    snap.status_generation = rec.generation
            except Exception:
                logger.warning(
                    "working memory status load failed execution=%s",
                    execution_id, exc_info=True,
                )

        if self._checkpoint is not None:
            try:
                snap.checkpoint = await self._checkpoint.load(execution_id)
            except Exception:
                logger.warning(
                    "working memory checkpoint load failed execution=%s",
                    execution_id, exc_info=True,
                )

        if self._awaitable is not None:
            try:
                snap.awaitable_tasks = await self._awaitable.list_by_execution(execution_id)
            except Exception:
                logger.warning(
                    "working memory awaitable load failed execution=%s",
                    execution_id, exc_info=True,
                )

        return snap

    async def load_for_resume(self, execution_id: str) -> WorkingMemorySnapshot | None:
        """加载执行态用于 resume。无 checkpoint 时返回 None。"""
        snap = await self.snapshot(execution_id)
        if snap.checkpoint is None and snap.status is None:
            return None
        return snap

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """保存 checkpoint（已完成节点结果）。"""
        if self._checkpoint is None:
            return
        await self._checkpoint.save(checkpoint)

    async def save_status(self, record: ExecutionStatusRecord) -> None:
        """保存执行状态。"""
        if self._status is None:
            return
        await self._status.save(record)

    async def save_awaitable(self, task: AwaitableTask) -> None:
        """保存可等待任务。"""
        if self._awaitable is None:
            return
        await self._awaitable.save(task)

    async def clear(self, execution_id: str) -> None:
        """清理执行的 Working Memory（任务结束后可选调用）。

        注意：通常不删除 checkpoint（保留用于 replay/forensic），
        仅清理 status 和已完成的 awaitable。
        """
        if self._status is not None:
            try:
                rec = await self._status.load(execution_id)
                if rec is not None and not rec.status.is_terminal:
                    await self._status.save(
                        ExecutionStatusRecord(
                            execution_id,
                            ExecutionStatus.SUCCEEDED,
                            generation=rec.generation,
                        )
                    )
            except Exception:
                logger.warning(
                    "working memory clear failed execution=%s",
                    execution_id, exc_info=True,
                )


__all__ = [
    "WorkingMemorySnapshot",
    "WorkingMemory",
]
