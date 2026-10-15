"""Control Plane API（V3 Phase 4）：执行控制面 HTTP 端点。

8 个操作：inspect / pause / resume / cancel / retry / requeue / recover / terminate。
状态转换矩阵校验：非法操作返回 409 Conflict。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/executions", tags=["control-plane"])


def _get_control_plane(request: Request):
    cp = getattr(request.app.state, "control_plane", None)
    if cp is None:
        raise HTTPException(status_code=503, detail="control plane not enabled (scheduler disabled)")
    return cp


@router.get("/{execution_id}")
async def inspect_execution(execution_id: str, request: Request):
    """查看执行完整快照。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return snapshot.to_dict()


@router.post("/{execution_id}/pause")
async def pause_execution(execution_id: str, request: Request):
    """暂停执行（仅 RUNNING 可暂停）。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    if snapshot.status is not None and snapshot.status.value != "running":
        raise HTTPException(
            status_code=409,
            detail=f"cannot pause: current status={snapshot.status.value} (only running can pause)",
        )
    success = await cp.pause(execution_id)
    if not success:
        raise HTTPException(status_code=409, detail="pause failed")
    return {"execution_id": execution_id, "status": "paused"}


@router.post("/{execution_id}/resume")
async def resume_execution(execution_id: str, request: Request):
    """恢复执行（仅 PAUSED 可恢复）。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    if snapshot.status is not None and snapshot.status.value != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"cannot resume: current status={snapshot.status.value} (only paused can resume)",
        )
    success = await cp.resume(execution_id)
    if not success:
        raise HTTPException(status_code=409, detail="resume failed")
    return {"execution_id": execution_id, "status": "running"}


@router.post("/{execution_id}/cancel")
async def cancel_execution(execution_id: str, request: Request):
    """取消执行（QUEUED 直接取消，RUNNING 标记 CANCEL_REQUESTED）。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    if snapshot.status is not None and snapshot.status.is_terminal:
        raise HTTPException(
            status_code=409,
            detail=f"cannot cancel: execution already terminal ({snapshot.status.value})",
        )
    success = await cp.cancel(execution_id)
    if not success:
        raise HTTPException(status_code=409, detail="cancel failed")
    return {"execution_id": execution_id, "status": "cancel_requested"}


@router.post("/{execution_id}/retry")
async def retry_execution(execution_id: str, request: Request):
    """重试执行（仅 FAILED / SUCCEEDED / CANCELLED 可 retry）。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    if snapshot.status is not None and not snapshot.status.is_terminal:
        raise HTTPException(
            status_code=409,
            detail=f"cannot retry: execution not terminal ({snapshot.status.value})",
        )
    new_id = await cp.retry(execution_id)
    if new_id is None:
        raise HTTPException(status_code=409, detail="retry failed")
    return {"old_execution_id": execution_id, "new_execution_id": new_id}


@router.post("/{execution_id}/terminate")
async def terminate_execution(execution_id: str, request: Request):
    """强制终止执行（非终态均可终止）。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    if snapshot.status is not None and snapshot.status.is_terminal:
        raise HTTPException(
            status_code=409,
            detail=f"already terminal ({snapshot.status.value})",
        )
    success = await cp.terminate(execution_id)
    if not success:
        raise HTTPException(status_code=409, detail="terminate failed")
    return {"execution_id": execution_id, "status": "failed"}


@router.post("/{execution_id}/requeue")
async def requeue_execution(execution_id: str, request: Request):
    """重新入队（保留原 execution_id；仅 failed / cancelled / dispatched 可 requeue）。

    与 retry 的区别：retry 开一条 ``:retry:N`` 新执行并保留失败历史，requeue 把同一条
    放回队列。COMPLETED（成功不该重跑）/ QUEUED（已在队列）/ RUNNING（仍在执行）返回 409。
    """
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    success = await cp.requeue(execution_id)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=(
                "cannot requeue: queue_status="
                f"{snapshot.queue_status.value if snapshot.queue_status else 'unknown'} "
                "(only failed / cancelled / dispatched can requeue)"
            ),
        )
    return {"execution_id": execution_id, "status": "queued"}


@router.post("/{execution_id}/recover")
async def recover_execution(execution_id: str, request: Request):
    """按 Effect Contract 跑一次恢复决策（retry / query_status / mark_failed / mark_human）。"""
    cp = _get_control_plane(request)
    snapshot = await cp.inspect(execution_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="execution not found")
    action = await cp.recover(execution_id)
    if action is None:
        raise HTTPException(
            status_code=409,
            detail="recover unavailable (SCHEDULER_RECOVERY_ENABLED is off)",
        )
    return {"execution_id": execution_id, "action": action}
