"""Human Task API（V3 补-1）：人工审批面。

三段链的第三段——创建在 `planner/protocol.py` 的 `__awaitable__`（`kind="human"`）分支，
挂起态在 `query_router`（写 `WAITING_HUMAN`），本文件是审批入口。

**审批人身份的口径**：`approver` 一律取服务端断言主体，**不接受请求体自报**。把审计主体
交回客户端正是 `session_router.py` 的 `operator = api_key or "default"` 那次整改要消除的形状
（见 `docs/plans/plan-audit-operator-principal-2026-10-03.md`）。请求体里的自由文本只进
`comment`。局限：ADR-0007 的身份层默认只 observe，故当前所有审批都记同一个服务端主体，
真·逐审批人身份要等身份层实际启用。
"""

from __future__ import annotations

import logging

from agent_runtime.human_task import HumanTaskDecision
from agent_runtime.workspace_registry import server_tenant_id
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent_server.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/human-tasks", tags=["human-task"])


class DecisionPayload(BaseModel):
    """审批载荷。刻意**不含 approver 字段**：审批人不由客户端自报（见模块 docstring）。"""

    comment: str = ""


def _approver() -> str:
    return server_tenant_id(get_settings().default_tenant_id)


def _store(request: Request):
    store = getattr(request.app.state, "human_task_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="human task store not configured")
    return store


def _resolver(request: Request):
    resolver = getattr(request.app.state, "human_task_resolver", None)
    if resolver is None:
        raise HTTPException(status_code=503, detail="human task resolver not configured")
    return resolver


def _view(task) -> dict:
    """AwaitableTask → 对外视图（只暴露审批需要的字段，不回传内部 metadata 全量）。"""
    metadata = task.metadata or {}
    return {
        "task_id": task.task_id,
        "execution_id": task.execution_id,
        "step_id": task.step_id,
        "state": task.state.value,
        "prompt": metadata.get("prompt"),
        "options": metadata.get("options"),
        "deadline": task.deadline,
        "submitted_by": metadata.get("submitted_by"),
        "completion_receipt": task.completion_receipt,
        "resume_payload": task.resume_payload,
    }


@router.get("/task/{task_id}")
async def get_task(task_id: str, request: Request):
    """查单个人工任务（含审批结果与 resume_payload）。"""
    task = await _store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _view(task)


@router.get("/{execution_id}")
async def list_pending(execution_id: str, request: Request):
    """列某执行下所有待审批任务（非终态的 HUMAN 任务）。"""
    tasks = await _store(request).list_pending(execution_id)
    return {"execution_id": execution_id, "pending": [_view(t) for t in tasks]}


@router.post("/{task_id}/approve")
async def approve(task_id: str, payload: DecisionPayload, request: Request):
    """批准：任务 → COMPLETED + resume_payload，且 WAITING_HUMAN → RUNNING。"""
    approver = _approver()
    try:
        task = await _resolver(request).resolve_and_resume(
            task_id, HumanTaskDecision.APPROVED, approver, payload.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info("human task approved task=%s approver=%s", task_id, approver)
    return {
        "task_id": task_id,
        "state": task.state.value,
        "decision": HumanTaskDecision.APPROVED.value,
        "approver": approver,
    }


@router.post("/{task_id}/reject")
async def reject(task_id: str, payload: DecisionPayload, request: Request):
    """驳回：任务 → FAILED，执行状态转终态 FAILED。"""
    approver = _approver()
    try:
        task = await _resolver(request).reject_and_fail(task_id, approver, payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info("human task rejected task=%s approver=%s", task_id, approver)
    return {
        "task_id": task_id,
        "state": task.state.value,
        "decision": HumanTaskDecision.REJECTED.value,
        "approver": approver,
    }
