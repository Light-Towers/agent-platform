"""Callback API（V3 Phase 3.4b）：外部系统回调端点。

接收外部异步任务完成回调，更新 AwaitableTask 状态 + 触发执行恢复。

幂等保证：同一 callback 重复到达不重复 resume（AwaitableTask 终态 no-op）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/callback", tags=["callback"])


class CallbackPayload(BaseModel):
    """外部回调载荷。"""

    result: dict | None = None
    error: str | None = None


@router.post("/{task_id}")
async def handle_callback(task_id: str, payload: CallbackPayload, request: Request):
    """外部回调：标记 AwaitableTask COMPLETED + 触发执行恢复。

    幂等：task 已 COMPLETED 时返回 200 不重复 resume。
    """
    awaitable_task_store = getattr(request.app.state, "awaitable_task_store", None)
    if awaitable_task_store is None:
        raise HTTPException(status_code=503, detail="awaitable task store not configured")

    from agent_runtime.awaitable_task import AwaitableState, can_transition

    task = await awaitable_task_store.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    if task.state.is_terminal:
        return {"status": "already_completed", "task_id": task_id}

    if not can_transition(task.state, AwaitableState.COMPLETED):
        raise HTTPException(
            status_code=409,
            detail=f"invalid state transition: {task.state.value} → completed",
        )

    # CAS: SUBMITTED/RUNNING → COMPLETED
    task.state = AwaitableState.COMPLETED
    task.resume_payload = payload.result or {}
    if payload.error:
        task.state = AwaitableState.FAILED
        task.completion_receipt = {"error": payload.error}
    import time

    task.completed_at = time.time()
    await awaitable_task_store.save(task)

    # 触发执行恢复
    checkpoint_store = getattr(request.app.state, "planner_runtime", None)
    if checkpoint_store is not None:
        checkpoint_store = getattr(checkpoint_store, "checkpoint_store", None)
    if checkpoint_store is not None and task.state == AwaitableState.COMPLETED:
        try:
            await _resume_execution(request.app.state, task)
        except Exception:
            logger.warning("resume execution failed for task %s", task_id, exc_info=True)

    return {"status": task.state.value, "task_id": task_id}


async def _resume_execution(app_state, task) -> None:
    """从 checkpoint 恢复执行：注入 resume_payload → re-run execution graph。

    1. load checkpoint → completed dict
    2. inject: completed[task.step_id] = task.resume_payload
    3. save checkpoint（updated completed）
    4. ExecutionStatus → RUNNING
    5. 实际 re-run 由 Scheduler / 手动触发（此处仅准备 checkpoint + 状态）
    """
    from agent_runtime.planner.durability import Checkpoint

    runtime = app_state.planner_runtime
    checkpoint_store = runtime.checkpoint_store
    status_store = getattr(app_state, "status_store", None)

    if checkpoint_store is None:
        logger.debug("no checkpoint store, skip resume")
        return

    cp = await checkpoint_store.load(task.execution_id)
    if cp is None:
        logger.warning("checkpoint not found for execution %s, cannot resume", task.execution_id)
        return

    # 注入挂起节点的结果
    completed = dict(cp.completed)
    completed[task.step_id] = task.resume_payload

    # 保存更新后的 checkpoint
    await checkpoint_store.save(
        Checkpoint(
            task.execution_id,
            completed,
            resumable=False,
            generation=cp.generation,
        )
    )

    # ExecutionStatus → RUNNING
    if status_store is not None:
        from agent_runtime.execution_status import ExecutionStatus, ExecutionStatusRecord

        try:
            await status_store.save(ExecutionStatusRecord(
                execution_id=task.execution_id,
                status=ExecutionStatus.RUNNING,
            ))
        except Exception:
            logger.debug("status save RUNNING on resume failed", exc_info=True)

    logger.info(
        "execution %s resumed: injected step=%s payload_keys=%s",
        task.execution_id,
        task.step_id,
        list(task.resume_payload.keys()) if task.resume_payload else [],
    )
