# -*- coding: utf-8 -*-
"""/sql/train 改转发 nl2sql /api/meta/ingest 用例（A 方案 Stage ③）。

钉五件事：
1. 未配置 NL2SQL_SERVICE_URL → 503（不静默）；
2. 全空 body → 400（契约不变）；
3. 转发 payload 形状：ddl/docs/examples + 服务端断言 tenant + workspace；
4. 响应 flag 语义 = "已摄入" + report 明细回传（历史调用方只读 flag 不变）；
5. 上游不可达 → 502；上游 4xx/5xx 原样透传状态码。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from agent_server.api.sql_router import sql_train
from agent_server.schemas import SqlTrainRequest


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _Client:
    """捕获 POST 的 (url, payload)，按脚本返回响应。"""

    def __init__(self, resp: _Resp, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, json: Any = None, **kwargs: Any) -> _Resp:
        self.calls.append((url, json or {}))
        if self._exc is not None:
            raise self._exc
        return self._resp


_INGEST_REPORT = {
    "columns": {"inserted": 2, "updated": 0},
    "examples": {"inserted": 1, "updated": 0},
    "tenant_id": "t-1",
    "workspace_id": "ws-a",
    "datasource_id": "dw",
    "skipped_ddl": [],
    "unmapped_docs": [],
    "skipped_examples": [],
}


def _settings(url: str = "http://nl2sql:8000") -> MagicMock:
    s = MagicMock()
    s.nl2sql_service_url = url
    s.default_tenant_id = "default-tenant"
    return s


async def test_train_unconfigured_503():
    with patch("agent_server.api.sql_router.get_settings", return_value=_settings("")):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await sql_train(SqlTrainRequest(ddl="CREATE TABLE t (id INT)"), _auth=None)
    assert exc_info.value.status_code == 503


async def test_train_empty_body_400():
    with patch("agent_server.api.sql_router.get_settings", return_value=_settings()):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await sql_train(SqlTrainRequest(), _auth=None)
    assert exc_info.value.status_code == 400


async def test_train_forwards_payload_and_returns_flags_plus_report():
    client = _Client(_Resp(200, _INGEST_REPORT))
    with patch("agent_server.api.sql_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.sql_router.get_pool", return_value=None), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await sql_train(
            SqlTrainRequest(
                ddl="CREATE TABLE t (id INT)",
                documentation="t 表的说明",
                question="q",
                sql="SELECT 1",
                workspace_id="ws-a",
            ),
            _auth=None,
        )
    url, payload = client.calls[0]
    assert url == "http://nl2sql:8000/api/meta/ingest"
    assert payload["ddl"] == "CREATE TABLE t (id INT)"
    assert payload["docs"] == "t 表的说明"
    assert payload["examples"] == [{"question": "q", "sql": "SELECT 1"}]
    assert payload["tenant_id"] == "default-tenant", "tenant 取服务端断言（不收请求体）"
    assert payload["workspace_id"] == "ws-a"

    assert resp.ddl_stored and resp.doc_stored and resp.example_stored
    assert resp.report == _INGEST_REPORT, "report 明细必须回传（flag 只答'喂了没'）"


async def test_train_upstream_unreachable_502():
    client = _Client(_Resp(200), exc=httpx.ConnectError("refused"))
    with patch("agent_server.api.sql_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.sql_router.get_pool", return_value=None), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await sql_train(SqlTrainRequest(ddl="CREATE TABLE t (id INT)"), _auth=None)
    assert exc_info.value.status_code == 502


async def test_train_upstream_error_status_propagates():
    client = _Client(_Resp(400, text="ddl / docs / examples 至少提供一项"))
    with patch("agent_server.api.sql_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.sql_router.get_pool", return_value=None), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await sql_train(SqlTrainRequest(ddl="CREATE TABLE t (id INT)"), _auth=None)
    assert exc_info.value.status_code == 400
    assert "至少提供一项" in str(exc_info.value.detail)
