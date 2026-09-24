"""会话管理路由：/session/revert + /history。"""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request

from agent_server.api.auth import resolve_thread_id, verify_api_key
from agent_server.config import get_settings
from agent_server.memory import recall_exact as _recall_exact
from agent_server.schemas import HistoryItem, HistoryResponse, RevertRequest, RevertResponse

router = APIRouter()


@router.get("/history", response_model=HistoryResponse)
async def history(
    session_id: str,
    keyword: str | None = None,
    limit: int | None = None,
    request: Request = None,
    api_key=Depends(verify_api_key),
):
    """精确回忆：按会话 thread_id 取回历史对话原文（优化 I）。

    与 /query 的语义召回（优化 H）正交：此处返回字面原文，支持关键词过滤，
    用于「找到我之前某次聊天里具体说了什么」。需 api_key 鉴权。
    """
    thread_id = resolve_thread_id(session_id, api_key)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None:
        raise HTTPException(status_code=503, detail="CHECKPOINTER_UNAVAILABLE")
    items = await _recall_exact.get_thread_history(
        checkpointer, thread_id, keyword=keyword, limit=limit
    )
    return HistoryResponse(
        thread_id=thread_id,
        count=len(items),
        items=[HistoryItem(**it) for it in items],
    )


@router.post("/session/revert", response_model=RevertResponse)
async def session_revert(
    req: RevertRequest,
    request: Request,
    api_key=Depends(verify_api_key),
):
    settings = get_settings()
    if not settings.revert_enabled:
        raise HTTPException(status_code=404, detail="REVERT_NOT_ENABLED")

    revert_handler = getattr(request.app.state, "revert_handler", None)
    if revert_handler is None:
        raise HTTPException(status_code=404, detail="REVERT_NOT_INITIALIZED")

    operator = api_key or "default"
    result = await revert_handler.revert(operator, req.session_id, req.checkpoint_id)

    if not result.success:
        if result.error == "CHECKPOINT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="CHECKPOINT_NOT_FOUND")
        if result.error == "FORBIDDEN":
            raise HTTPException(status_code=403, detail="FORBIDDEN")
        raise HTTPException(status_code=500, detail=result.error or "REVERT_FAILED")

    from datetime import datetime

    return RevertResponse(
        session_id=result.session_id,
        checkpoint_id=result.checkpoint_id,
        context_summary=result.context_summary,
        reverted_at=datetime.now(UTC).isoformat(),
    )
