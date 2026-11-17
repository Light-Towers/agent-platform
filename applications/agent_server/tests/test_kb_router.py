# -*- coding: utf-8 -*-
"""/kb/* 代理（批 2a）用例：钉八件事。

1. 未配置 KNOWLEDGE_SERVICE_URL → 503（不静默）；
2. R5：Form tenant_id 非空且 ≠ 服务端断言租户 → AppError 403 TENANT_MISMATCH；
3. R5 正向：断言租户一致 ⇒ 转发，且转发的 form **不含 tenant_id**（KS 只见签名头）；
4. 未配 INTERNAL_HMAC_KEY ⇒ 503 拒发，零转发；
5. 签名头形状：X-Internal-Tenant；配了 KNOWLEDGE_SERVICE_KEY 才有 X-API-Key；
6. 上游不可达 → 502；上游 ≥400 → 状态码 + 文案透传；
7. PATCH /kb/{id}/status → KS POST /reimport（form 形状钉死）；
8. GET /kb/documents → KS GET /documents?limit=（透传 JSON）。
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from agent_core.guardrails.errors import AppError
from agent_runtime.identity import IdentityError
from agent_server.api.kb_router import kb_documents, kb_history, kb_status, kb_upload
from agent_server.schemas import KbStatusRequest


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _Client:
    """捕获 POST/GET 的 (url, data/files/params, headers)，按脚本返回响应。"""

    def __init__(self, resp: _Resp, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc
        self.posts: list[tuple[str, dict, Any, dict | None]] = []
        self.gets: list[tuple[str, dict | None, dict | None]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, data: Any = None, **kwargs: Any) -> _Resp:
        self.posts.append((url, data or {}, kwargs.get("files"), kwargs.get("headers")))
        if self._exc is not None:
            raise self._exc
        return self._resp

    async def get(self, url: str, params: dict | None = None, **kwargs: Any) -> _Resp:
        self.gets.append((url, params, kwargs.get("headers")))
        if self._exc is not None:
            raise self._exc
        return self._resp


class _Up:
    """UploadFile 鸭子替身（直调端点不走 FastAPI 验证，只需 filename/file/content_type）。"""

    def __init__(self, filename: str = "a.pdf", content: bytes = b"pdf-bytes") -> None:
        self.filename = filename
        self.file = io.BytesIO(content)
        self.content_type = "application/pdf"


def _settings(url: str = "http://ks:8900", key: str = "") -> MagicMock:
    s = MagicMock()
    s.knowledge_service_url = url
    s.knowledge_service_key = key
    s.default_tenant_id = "default-tenant"
    return s


_UPLOAD_FORM = dict(
    tenant_id="",
    scope_type="PRIVATE",
    tenant_type="",
    effective_from="",
    effective_to="",
    version="",
    authority="",
    status="DRAFT",
    constraint_kind="",
    enable_item_name_recognition=True,
    knowledge_id="k-1",
    exhibition_id="",
    venue_id="",
)


async def test_upload_unconfigured_url_503():
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings("")):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 503


async def test_upload_cross_tenant_form_403():
    """R5：表单 tenant_id 非空且 ≠ 断言租户 ⇒ 403 TENANT_MISMATCH（信封统一）。"""
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()):
        with pytest.raises(AppError) as exc_info:
            await kb_upload(files=[_Up()], **{**_UPLOAD_FORM, "tenant_id": "other-tenant"}, _auth=None, _feature=None)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "TENANT_MISMATCH"


async def test_upload_forwards_files_and_strips_tenant_id():
    client = _Client(_Resp(200, {"code": 200, "message": "ok", "task_ids": ["t1"]}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_upload(files=[_Up()], **{**_UPLOAD_FORM, "tenant_id": "default-tenant"}, _auth=None, _feature=None)
    url, data, files, headers = client.posts[0]
    assert url == "http://ks:8900/upload"
    assert "tenant_id" not in data, "R5：归属走签名头，转发剥掉表单租户（KS 只见签名头）"
    assert data["scope_type"] == "PRIVATE"
    assert data["knowledge_id"] == "k-1"
    assert data["status"] == "DRAFT"
    assert data["enable_item_name_recognition"] == "true"
    assert files is not None and files[0][0] == "files", "多文件经 files= 转发（浏览器禁直连 KS，唯一入口在本代理）"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}, "未配 KNOWLEDGE_SERVICE_KEY ⇒ 只发签名头"
    assert resp == {"code": 200, "message": "ok", "task_ids": ["t1"]}, "KS 响应透传（契约形状不重造）"


async def test_upload_no_hmac_key_503_refuses_unsigned_forward():
    client = _Client(_Resp(200, {"code": 200, "task_ids": []}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch(
             "agent_server.api.kb_router.sign_internal_header",
             side_effect=IdentityError("未配置 INTERNAL_HMAC_KEY（内部签名头无法签发）"),
         ), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 503
    assert "INTERNAL_HMAC_KEY" in str(exc_info.value.detail)
    assert client.posts == [], "拒发即零转发——不能裸转未签名请求"


async def test_upload_service_key_becomes_api_key_header():
    """配了 KNOWLEDGE_SERVICE_KEY ⇒ X-API-Key 随签名头一起发（KS 护栏认这个头）。"""
    client = _Client(_Resp(200, {"code": 200, "task_ids": []}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings(key="ks-secret")), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    _, _, _, headers = client.posts[0]
    assert headers == {"X-Internal-Tenant": "v1.test.sig", "X-API-Key": "ks-secret"}


async def test_upload_upstream_unreachable_502():
    client = _Client(_Resp(200), exc=httpx.ConnectError("refused"))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 502


async def test_upload_upstream_error_status_propagates():
    """上游 4xx/5xx 原样透传（含 100MB 超限的 413 具名文案）。"""
    client = _Client(_Resp(413, text='{"detail":"文件超出上传上限（100 MB）"}'))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 413
    assert "100 MB" in str(exc_info.value.detail)


async def test_status_forwards_to_reimport_with_form_shape():
    """PATCH /kb/{id}/status → KS POST /reimport（form：knowledge_id/status/三字段）。"""
    client = _Client(_Resp(200, {"code": 200, "knowledge_id": "k-1", "from": "REVIEWING", "to": "PUBLISHED", "task_id": "t9"}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_status(
            "k-1",
            KbStatusRequest(status="PUBLISHED", authority="cma", effective_from="2026-01-01", effective_to="2027-01-01"),
            _auth=None,
            _feature=None,
        )
    url, data, files, headers = client.posts[0]
    assert url == "http://ks:8900/reimport"
    assert data == {
        "knowledge_id": "k-1",
        "status": "PUBLISHED",
        "authority": "cma",
        "effective_from": "2026-01-01",
        "effective_to": "2027-01-01",
    }
    assert files is None, "reimport 无文件载荷"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp["task_id"] == "t9"


async def test_documents_forwards_get_with_limit():
    client = _Client(_Resp(200, {"code": 200, "tenant_id": "default-tenant", "total": 0, "documents": []}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_documents(limit=50, _auth=None, _feature=None)
    url, params, headers = client.gets[0]
    assert url == "http://ks:8900/documents"
    assert params == {"limit": 50}
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == {"code": 200, "tenant_id": "default-tenant", "total": 0, "documents": []}


async def test_history_forwards_get_with_limit():
    payload = {"code": 200, "tenant_id": "default-tenant", "total": 1,
               "items": [{"task_id": "t1", "filename": "a.pdf", "status": "completed", "summary": {}}]}
    client = _Client(_Resp(200, payload))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_history(limit=30, _auth=None, _feature=None)
    url, params, headers = client.gets[0]
    assert url == "http://ks:8900/history"
    assert params == {"limit": 30}
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == payload
