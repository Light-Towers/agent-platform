"""会话标题端点契约单测（router 层，monkeypatch 掉鉴权/池/service，不拉起完整 app）。

覆盖守门判据：
- PATCH 成功 → 200，回填服务端返回的 title_source=manual；
- PATCH 归属不匹配（service 未命中）→ 404 SESSION_NOT_FOUND；
- PATCH 空白标题（trim 后为空）→ 422 TITLE_EMPTY；
- GET 列表响应透传每项的 title_source。
"""

from __future__ import annotations

import asyncio

import pytest
from agent_server.api import sessions_router as router
from agent_server.schemas import SessionUpdateTitleRequest
from fastapi import HTTPException


def _patch_scope(monkeypatch, *, set_ok, session_row=None):
    monkeypatch.setattr(router, "_scope", lambda: ("acme", "alice"))
    monkeypatch.setattr(router, "get_pool", lambda: object())

    async def _set(*args, **kwargs):
        return set_ok

    async def _get(*args, **kwargs):
        return session_row

    monkeypatch.setattr(router._svc, "set_session_title", _set)
    monkeypatch.setattr(router._svc, "get_session", _get)


def test_patch_title_success_backfills_manual(monkeypatch):
    row = {
        "session_id": "s1", "title": "我的标题", "workspace_id": "default",
        "title_source": "manual", "created_at": None, "last_active_at": None,
    }
    _patch_scope(monkeypatch, set_ok=True, session_row=row)
    info = asyncio.run(router.update_session_title("s1", SessionUpdateTitleRequest(title="我的标题")))
    assert info.title == "我的标题"
    assert info.title_source == "manual"


def test_patch_title_missing_session_maps_404(monkeypatch):
    _patch_scope(monkeypatch, set_ok=False, session_row=None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.update_session_title("s1", SessionUpdateTitleRequest(title="改名")))
    assert exc.value.status_code == 404
    assert exc.value.detail == "SESSION_NOT_FOUND"


def test_patch_title_blank_maps_422(monkeypatch):
    _patch_scope(monkeypatch, set_ok=True, session_row=None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.update_session_title("s1", SessionUpdateTitleRequest(title="   ")))
    assert exc.value.status_code == 422


def test_list_sessions_passes_title_source(monkeypatch):
    monkeypatch.setattr(router, "_scope", lambda: ("acme", "alice"))
    monkeypatch.setattr(router, "get_pool", lambda: object())

    async def _list(*args, **kwargs):
        return [
            {
                "session_id": "s1", "title": "自动标题", "workspace_id": "default",
                "title_source": "auto", "created_at": None, "last_active_at": None,
            },
            {
                "session_id": "s2", "title": "手改标题", "workspace_id": "default",
                "title_source": "manual", "created_at": None, "last_active_at": None,
            },
        ]

    monkeypatch.setattr(router._svc, "list_sessions", _list)
    resp = asyncio.run(router.list_sessions())
    assert [s.title_source for s in resp.sessions] == ["auto", "manual"]
