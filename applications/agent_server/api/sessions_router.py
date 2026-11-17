# -*- coding: utf-8 -*-
"""多会话目录端点：GET/POST/DELETE /sessions。

归属一律取服务端断言（org=server_tenant_id、user=asserted_user_id），客户端只持有
服务端签发的 session_id；任何跨归属访问映射 404（不泄露"存在但非你所有"）。
"""

from agent_runtime.db import get_pool
from agent_runtime.workspace_registry import asserted_user_id, server_tenant_id
from fastapi import APIRouter, Depends, HTTPException

from agent_server.api import sessions_service as _svc
from agent_server.api.auth import require_feature, resolve_thread_id, verify_api_key
from agent_server.config import get_settings
from agent_server.schemas import (
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionInfo,
    SessionListResponse,
    SessionUpdateTitleRequest,
)

router = APIRouter()


def _scope() -> tuple[str, str]:
    """服务端断言的归属二元组（org_id, user_id）；与 query_router 同口径。"""
    settings = get_settings()
    org_id = server_tenant_id(settings.default_tenant_id)
    user_id = asserted_user_id() or ""
    return org_id, user_id


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(_auth=Depends(verify_api_key), _feature=Depends(require_feature("chat.run"))):
    org_id, user_id = _scope()
    rows = await _svc.list_sessions(get_pool(), org_id=org_id, user_id=user_id)
    return SessionListResponse(
        sessions=[SessionInfo(
            session_id=r["session_id"], title=r["title"], workspace_id=r["workspace_id"],
            title_source=r.get("title_source", _svc.TITLE_SOURCE_DEFAULT),
            created_at=r.get("created_at"), last_active_at=r.get("last_active_at"),
        ) for r in rows],
        count=len(rows),
    )


@router.post("/sessions", response_model=SessionInfo, status_code=201)
async def create_session(
    req: SessionCreateRequest,
    _auth=Depends(verify_api_key),  # 401 先于 403
    _feature=Depends(require_feature("chat.run")),
):
    org_id, user_id = _scope()
    row = await _svc.create_session(
        get_pool(), org_id=org_id, user_id=user_id,
        base_thread_id=resolve_thread_id(None),
        workspace_id=req.workspace_id or "default", title=req.title,
    )
    return SessionInfo(
        session_id=row["session_id"], title=row["title"], workspace_id=row["workspace_id"],
        title_source=row.get("title_source", _svc.TITLE_SOURCE_DEFAULT),
        created_at=row.get("created_at"), last_active_at=row.get("last_active_at"),
    )


@router.patch("/sessions/{session_id}", response_model=SessionInfo)
async def update_session_title(
    session_id: str,
    req: SessionUpdateTitleRequest,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("chat.run")),
):
    """手动改标题：无条件写 title_source=manual，之后自动生成器永不覆盖。"""
    org_id, user_id = _scope()
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="TITLE_EMPTY")
    updated = await _svc.set_session_title(
        get_pool(), session_id, title, org_id=org_id, user_id=user_id,
        source=_svc.TITLE_SOURCE_MANUAL,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    row = await _svc.get_session(get_pool(), session_id, org_id=org_id, user_id=user_id)
    return SessionInfo(
        session_id=row["session_id"], title=row["title"], workspace_id=row["workspace_id"],
        title_source=row.get("title_source", _svc.TITLE_SOURCE_MANUAL),
        created_at=row.get("created_at"), last_active_at=row.get("last_active_at"),
    )


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("chat.run")),
):
    org_id, user_id = _scope()
    deleted = await _svc.delete_session(get_pool(), session_id, org_id=org_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return SessionDeleteResponse(session_id=session_id, deleted=True)
