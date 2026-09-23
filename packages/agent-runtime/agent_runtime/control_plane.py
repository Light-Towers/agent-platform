"""Execution Control Plane（V3-5B）：人可运营的执行控制面。

现状（v3 之前）：Trajectory / Checkpoint / Events / OTel / Audit / Lease / SideEffects
数据已存在，但未形成"人可运营 Execution"的控制面。

本模块把数据变成可操作的面：
- ``ExecutionSnapshot``：一次执行的完整快照（status / owner / generation / checkpoint / external tasks / ...）；
- ``ControlPlane``：inspect / pause / resume / cancel / retry / terminate 操作。

底层基础已具备（Trajectory/Replay/Checkpoint/Status/Scheduler），这一步是组合而非从零建。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.execution_scheduler import (
    ExecutionRequest,
    ExecutionScheduler,
    QueueStatus,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    ExecutionStatusStore,
    InvalidStatusTransition,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionSnapshot:
    """一次执行的完整快照（control plane inspect 返回）。"""

    execution_id: str
    tenant_id: str | None = None
    status: ExecutionStatus | None = None
    queue_status: QueueStatus | None = None
    current_step: str | None = None
    owner: str | None = None
    generation: int | None = None
    attempt: int = 0
    created_at: float | None = None
    dispatched_at: float | None = None
    worker_id: str | None = None
    priority: str | None = None
    checkpoint_summary: dict[str, Any] | None = None
    external_tasks: list[dict[str, Any]] = field(default_factory=list)
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value if self.status else None,
            "queue_status": self.queue_status.value if self.queue_status else None,
            "current_step": self.current_step,
            "owner": self.owner,
            "generation": self.generation,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
            "worker_id": self.worker_id,
            "priority": self.priority,
            "checkpoint_summary": self.checkpoint_summary,
            "external_tasks": self.external_tasks,
            "side_effects": self.side_effects,
            "errors": self.errors,
            "metadata": self.metadata,
        }


class ControlPlane:
    """Execution Control Plane：人可运营的执行控制面。

    组合 SchedulerStore + ExecutionStatusStore + CheckpointStore + AwaitableTaskStore，
    提供统一的查询和控制接口。
    """

    def __init__(
        self,
        scheduler: ExecutionScheduler,
        status_store: ExecutionStatusStore | None = None,
        checkpoint_store: Any = None,
        awaitable_store: Any = None,
    ) -> None:
        self._scheduler = scheduler
        self._status_store = status_store
        self._checkpoint_store = checkpoint_store
        self._awaitable_store = awaitable_store

    async def inspect(self, execution_id: str) -> ExecutionSnapshot | None:
        """查看一次执行的完整快照。"""
        req = await self._scheduler.get(execution_id)
        if req is None:
            return None

        snapshot = ExecutionSnapshot(
            execution_id=execution_id,
            tenant_id=req.tenant_id,
            queue_status=req.status,
            created_at=req.created_at,
            dispatched_at=req.dispatched_at,
            worker_id=req.worker_id,
            priority=req.priority.value,
            attempt=int(req.metadata.get("recovery_attempts", 0)),
            metadata=dict(req.metadata),
        )

        if self._status_store is not None:
            status_rec = await self._status_store.load(execution_id)
            if status_rec is not None:
                snapshot.status = status_rec.status
                snapshot.generation = status_rec.generation

        if self._checkpoint_store is not None:
            try:
                cp = await self._checkpoint_store.load(execution_id)
                if cp is not None:
                    snapshot.checkpoint_summary = {
                        "completed_nodes": list(cp.completed.keys()),
                        "node_count": len(cp.completed),
                        "resumable": cp.resumable,
                        "generation": cp.generation,
                        "state_schema_version": cp.state_schema_version,
                    }
                    snapshot.generation = cp.generation
            except Exception:  # noqa: BLE001
                logger.warning(
                    "control plane checkpoint load failed execution=%s",
                    execution_id,
                    exc_info=True,
                )

        if self._awaitable_store is not None:
            try:
                tasks = await self._awaitable_store.list_by_execution(execution_id)
                snapshot.external_tasks = [
                    {
                        "task_id": t.task_id,
                        "kind": t.kind.value,
                        "state": t.state.value,
                        "provider": t.provider,
                        "provider_task_id": t.provider_task_id,
                    }
                    for t in tasks
                ]
            except Exception:  # noqa: BLE001
                logger.warning(
                    "control plane awaitable load failed execution=%s",
                    execution_id,
                    exc_info=True,
                )

        return snapshot

    async def pause(self, execution_id: str) -> bool:
        """暂停执行（RUNNING → PAUSED）。"""
        if self._status_store is None:
            return False
        try:
            current = await self._status_store.load(execution_id)
            if current is None or current.status is not ExecutionStatus.RUNNING:
                return False
            await self._status_store.save(
                ExecutionStatusRecord(
                    execution_id,
                    ExecutionStatus.PAUSED,
                    generation=current.generation,
                )
            )
            logger.info("control plane pause execution=%s", execution_id)
            return True
        except (InvalidStatusTransition, Exception):
            logger.warning("control plane pause failed execution=%s", execution_id, exc_info=True)
            return False

    async def resume(self, execution_id: str) -> bool:
        """恢复执行（PAUSED → RUNNING）。"""
        if self._status_store is None:
            return False
        try:
            current = await self._status_store.load(execution_id)
            if current is None or current.status is not ExecutionStatus.PAUSED:
                return False
            await self._status_store.save(
                ExecutionStatusRecord(
                    execution_id,
                    ExecutionStatus.RUNNING,
                    generation=current.generation,
                )
            )
            logger.info("control plane resume execution=%s", execution_id)
            return True
        except (InvalidStatusTransition, Exception):
            logger.warning("control plane resume failed execution=%s", execution_id, exc_info=True)
            return False

    async def cancel(self, execution_id: str) -> bool:
        """取消执行。

        QUEUED → 直接从调度队列取消；
        RUNNING → 标记 CANCEL_REQUESTED（Worker 下次 checkpoint 时检查并停止）。
        """
        req = await self._scheduler.get(execution_id)
        if req is None:
            return False

        if req.status is QueueStatus.QUEUED:
            return await self._scheduler.cancel(execution_id)

        if req.status in (QueueStatus.DISPATCHED, QueueStatus.RUNNING):
            if self._status_store is not None:
                try:
                    current = await self._status_store.load(execution_id)
                    if current is not None and current.status is ExecutionStatus.RUNNING:
                        await self._status_store.save(
                            ExecutionStatusRecord(
                                execution_id,
                                ExecutionStatus.CANCEL_REQUESTED,
                                generation=current.generation,
                            )
                        )
                        logger.info("control plane cancel_request execution=%s", execution_id)
                        return True
                except (InvalidStatusTransition, Exception):  # noqa: BLE001 - best-effort terminate
                    logger.warning(
                        "control plane cancel failed execution=%s", execution_id, exc_info=True
                    )
                    return False
            await self._scheduler.complete(execution_id, QueueStatus.CANCELLED)
            return True

        return False

    async def retry(self, execution_id: str) -> str | None:
        """重试执行：标记旧执行 FAILED + 重新入队。返回新 execution_id。"""
        req = await self._scheduler.get(execution_id)
        if req is None:
            return None

        await self._scheduler.complete(execution_id, QueueStatus.FAILED)

        attempt = int(req.metadata.get("recovery_attempts", 0)) + 1
        new_id = f"{execution_id}:retry:{attempt}"
        new_metadata = dict(req.metadata)
        new_metadata["recovery_attempts"] = attempt
        new_metadata["recovered_from"] = execution_id

        new_req = ExecutionRequest(
            execution_id=new_id,
            tenant_id=req.tenant_id,
            session_id=req.session_id,
            user_id=req.user_id,
            priority=req.priority,
            resource_hints=dict(req.resource_hints),
            metadata=new_metadata,
        )
        try:
            await self._scheduler.submit(new_req)
            logger.info("control plane retry execution=%s → %s", execution_id, new_id)
            return new_id
        except Exception:  # noqa: BLE001
            logger.warning("control plane retry failed execution=%s", execution_id, exc_info=True)
            return None

    async def terminate(self, execution_id: str) -> bool:
        """强制终止执行（无论状态，直接标记 FAILED/CANCELLED）。"""
        req = await self._scheduler.get(execution_id)
        if req is None:
            return False

        if req.status.is_terminal:
            return True

        await self._scheduler.complete(execution_id, QueueStatus.FAILED)

        if self._status_store is not None:
            try:
                current = await self._status_store.load(execution_id)
                if current is not None and not current.status.is_terminal:
                    await self._status_store.save(
                        ExecutionStatusRecord(
                            execution_id,
                            ExecutionStatus.FAILED,
                            generation=current.generation,
                            reason="terminated_by_control_plane",
                        )
                    )
            except (InvalidStatusTransition, Exception):  # noqa: BLE001 - best-effort terminate
                pass

        logger.info("control plane terminate execution=%s", execution_id)
        return True


__all__ = [
    "ExecutionSnapshot",
    "ControlPlane",
]
