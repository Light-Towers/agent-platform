# -*- coding: utf-8 -*-
"""上传端点 multipart 契约测试：session_id 必须是 Form 字段（防退回 query 参数导致前端传图失败）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_core.guardrails.errors import install_error_handlers
from agent_server.api.auth import require_feature, verify_api_key
from agent_server.api.chat_router import router


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)  # 生产同款：AppError → 统一 4xx 信封
    app.include_router(router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[require_feature("chat.run")] = lambda: None
    return TestClient(app)


class _NoStore:
    async def save_image(self, ref, tenant, session_id, content, content_type):
        self.saved = (ref, tenant, session_id, len(content))
        return None


def test_multipart_session_id_recognized(monkeypatch):
    """回归：session_id 用 Form 声明，前端 FormData.append 才能传进来（否则 SESSION_ID_REQUIRED）。"""
    store = _NoStore()
    monkeypatch.setattr("agent_server.api.chat_router._store.save_image", store.save_image)
    client = _client()
    resp = client.post(
        "/chat/upload-image",
        files={"file": ("a.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        data={"session_id": "sess-123"},
    )
    assert resp.status_code == 200, resp.text
    assert "image_ref" in resp.json()
    assert store.saved[2] == "sess-123"


def test_reject_non_image(monkeypatch):
    client = _client()
    resp = client.post(
        "/chat/upload-image",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"session_id": "sess-123"},
    )
    assert resp.status_code == 415


def test_reject_missing_session_id(monkeypatch):
    client = _client()
    resp = client.post(
        "/chat/upload-image",
        files={"file": ("a.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        data={},
    )
    assert resp.status_code == 400
