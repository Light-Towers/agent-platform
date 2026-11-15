# -*- coding: utf-8 -*-
"""/datasources/* 代理（G3 刀 3）用例：钉转发纪律。

1. 未配置 NL2SQL_SERVICE_URL → 503（不静默）；
2. 未配 INTERNAL_HMAC_KEY ⇒ 503 拒发，零转发；
3. 签名头形状：X-Internal-Tenant；
4. 上游不可达 → 502；上游 ≥400 → 状态码 + 文案透传；
5. GET /datasources → nl2sql GET /api/meta/datasources；
6. POST /datasources → nl2sql POST /api/meta/datasources（body 透传）；
7. PATCH /datasources/{id} → nl2sql PATCH /api/meta/datasources/{id}（body 透传）；
8. POST /datasources/{id}/default → nl2sql POST /api/meta/datasources/{id}/default；
9. 上游非 JSON 响应 → 返回 {}（不抛）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from agent_runtime.identity import IdentityError
from agent_server.api.datasources_router import (
    proxy_create,
    proxy_list,
    proxy_set_default,
    proxy_update,
)


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "", boom: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self._boom = boom

    def json(self) -> dict:
        if self._boom:
            raise ValueError("not json")
        return self._payload


class _Client:
    """捕获 request(method, url, json, headers)，按脚本返回响应。"""

    def __init__(self, resp: _Resp, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc
        self.calls: list[tuple[str, str, Any, dict | None]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def request(self, method: str, url: str, json: Any = None, headers: dict | None = None, **kwargs: Any) -> _Resp:
        self.calls.append((method, url, json, headers))
        if self._exc is not None:
            raise self._exc
        return self._resp


class _Req:
    """Request 鸭子替身（端点直调不走 FastAPI 验证，只需 .json()）。"""

    def __init__(self, body: dict | None = None) -> None:
        self._body = body or {}

    async def json(self) -> dict:
        return self._body


def _settings(url: str = "http://nl2sql:8000", key: str = "") -> MagicMock:
    s = MagicMock()
    s.nl2sql_service_url = url
    s.default_tenant_id = "default-tenant"
    return s


async def test_list_unconfigured_url_503():
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings("")):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await proxy_list(_auth=None, _feature=None)
    assert exc_info.value.status_code == 503


async def test_no_hmac_key_503_refuses_unsigned_forward():
    client = _Client(_Resp(200, {}))
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", side_effect=IdentityError("no key")), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await proxy_list(_auth=None, _feature=None)
    assert exc_info.value.status_code == 503
    assert "INTERNAL_HMAC_KEY" in str(exc_info.value.detail)
    assert client.calls == [], "拒发即零转发——不能裸转未签名请求"


async def test_list_forwards_to_nl2sql_with_signed_header():
    client = _Client(_Resp(200, {"code": 200, "datasources": []}))
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await proxy_list(_auth=None, _feature=None)
    method, url, body, headers = client.calls[0]
    assert method == "GET"
    assert url == "http://nl2sql:8000/api/meta/datasources"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == {"code": 200, "datasources": []}


async def test_create_forwards_body():
    client = _Client(_Resp(200, {"code": 200, "id": "ds-1"}))
    body = {"name": "pg", "dsn": "postgres://x"}
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await proxy_create(_Req(body), _auth=None, _feature=None)
    method, url, fwd, headers = client.calls[0]
    assert method == "POST"
    assert url == "http://nl2sql:8000/api/meta/datasources"
    assert fwd == body, "请求体原样透传（不重造）"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == {"code": 200, "id": "ds-1"}


async def test_update_forwards_patch_with_id_and_body():
    client = _Client(_Resp(200, {"code": 200}))
    body = {"dsn": "postgres://y"}
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await proxy_update("ds-9", _Req(body), _auth=None, _feature=None)
    method, url, fwd, headers = client.calls[0]
    assert method == "PATCH"
    assert url == "http://nl2sql:8000/api/meta/datasources/ds-9"
    assert fwd == body
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == {"code": 200}


async def test_set_default_forwards_post():
    client = _Client(_Resp(200, {"code": 200, "default": "ds-9"}))
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await proxy_set_default("ds-9", _auth=None, _feature=None)
    method, url, body, headers = client.calls[0]
    assert method == "POST"
    assert url == "http://nl2sql:8000/api/meta/datasources/ds-9/default"
    assert body is None
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == {"code": 200, "default": "ds-9"}


async def test_upstream_unreachable_502():
    client = _Client(_Resp(200), exc=httpx.ConnectError("refused"))
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await proxy_list(_auth=None, _feature=None)
    assert exc_info.value.status_code == 502


async def test_upstream_error_status_propagates():
    client = _Client(_Resp(409, text='{"detail":"数据源已存在"}'))
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await proxy_create(_Req({"name": "x"}), _auth=None, _feature=None)
    assert exc_info.value.status_code == 409
    assert "数据源已存在" in str(exc_info.value.detail)


async def test_non_json_response_returns_empty_dict():
    client = _Client(_Resp(200, boom=True))
    with patch("agent_server.api.datasources_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.datasources_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await proxy_list(_auth=None, _feature=None)
    assert resp == {}, "上游非 JSON ⇒ 返回 {}（不抛）"
