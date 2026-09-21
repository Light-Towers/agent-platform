"""server.py 端点测试（Web 控制台 + encode-context + /api/query 端到端）。"""

from __future__ import annotations

import httpx
import pytest

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.middleware.context_codec import encode_base64
from exhibition_agent.mock_server.warehouse_mock import create_mock_app
from exhibition_agent.server import app
from exhibition_agent.testing_helpers import ctx, ctx_header, make_context_payload


def _patch_warehouse_client(monkeypatch, transport: httpx.ASGITransport) -> None:
    """让 server 内部 new 的 WarehouseClient 走 mock transport（不依赖真 9100 端口）。"""

    def _factory(base_url: str = "", **kwargs):
        return WarehouseClient(base_url=base_url, transport=transport, **kwargs)

    monkeypatch.setattr("exhibition_agent.server.WarehouseClient", _factory)


@pytest.fixture
async def server_transport() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=app)


async def test_index_returns_html(server_transport):
    """GET / 返回 Web 控制台 HTML。"""
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "exhibition-agent" in resp.text
    assert "text/html" in resp.headers.get("content-type", "")


async def test_encode_context_returns_header(server_transport):
    """POST /api/encode-context 返回编码后的 header + mode。"""
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post("/api/encode-context", json=context.model_dump(mode="json"))
    assert resp.status_code == 200
    data = resp.json()
    assert "header" in data
    assert "mode" in data
    assert len(data["header"]) > 0


async def test_encode_context_invalid_returns_422(server_transport):
    """POST /api/encode-context 非法字段 → 422。"""
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post("/api/encode-context", json={"user_id": ""})
    assert resp.status_code == 422


async def test_encode_context_strict_mode_returns_403(server_transport, monkeypatch):
    """P1 安全：STRICT 档调用 /api/encode-context → 403。"""
    monkeypatch.setattr("exhibition_agent.server.settings.execution_mode", "STRICT")
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post("/api/encode-context", json=context.model_dump(mode="json"))
    assert resp.status_code == 403


async def test_health(server_transport):
    """GET /health 返回 ok。"""
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_query_ignores_client_context_mode_header(server_transport, monkeypatch):
    """P1 安全：客户端发 X-Context-Mode: base64 头被忽略，按服务端配置（jwt）解析。

    若客户端头生效（bug），base64 编码的上下文会被按 base64 解析 → 放行进入 warehouse 调用。
    客户端头被忽略时，按 jwt 解析 base64 字符串 → 401 AUTH_CONTEXT_INVALID。
    """
    monkeypatch.setattr("exhibition_agent.server.settings.context_mode", "jwt")
    payload = make_context_payload()
    base64_header = encode_base64(payload)
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "test", "params": {}},
            headers={
                "X-Execution-Context": base64_header,
                "X-Context-Mode": "base64",
            },
        )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "AUTH_CONTEXT_INVALID"


# ---------------------------------------------------------------------------
# /api/query 端到端（成功 / 403 空 scopes / INV-10 指标待接入）
# ---------------------------------------------------------------------------
async def test_query_success_returns_200(server_transport, monkeypatch):
    """合法 JWT + normal_200 → 200 + readiness=READY + answer 含场馆名。"""
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询场馆排期", "params": {"venue_id": "vn-001"}},
            headers={
                "X-Execution-Context": ctx_header(context),
                "X-Mock-Scenario": "normal_200",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["readiness"] == "READY"
    assert "保利世贸博览馆" in data["answer"]
    assert data["error_code"] is None


async def test_query_empty_scopes_returns_403(server_transport, monkeypatch):
    """空 scopes + venue. 前缀 skill → 403 SCOPE_DENIED（资源级判定）。"""
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    context = ctx(scopes=[])
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询场馆排期", "params": {}},
            headers={"X-Execution-Context": ctx_header(context)},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "SCOPE_DENIED"


async def test_query_metric_not_verified_answers_pending(server_transport, monkeypatch):
    """INV-10：metric_not_verified → 200 + answer='该指标待接入' + error_code=METRIC_NOT_VERIFIED。"""
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询展位销售率", "params": {"metric": "sales_rate"}},
            headers={
                "X-Execution-Context": ctx_header(context),
                "X-Mock-Scenario": "metric_not_verified",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "该指标待接入"
    assert data["error_code"] == "METRIC_NOT_VERIFIED"
    assert data["readiness"] == "NOT_CONNECTED"
    assert data["sql_statements"] == []
