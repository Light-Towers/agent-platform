"""server.py 端点测试（Web 控制台 + encode-context + /api/query 端到端）。"""

from __future__ import annotations

import importlib.util

import httpx
import pytest

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.middleware.context_codec import encode_base64, encode_jwt
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


# ---------------------------------------------------------------------------
# W3：skill 级错误码按契约 §C2 HTTP 映射（401/403 不再吞成 200）
# ---------------------------------------------------------------------------
async def test_query_warehouse_auth_error_maps_401(server_transport, monkeypatch):
    """warehouse 侧 401（AUTH_CONTEXT_MISSING）→ 平台 401，不再吞成 200（W3）。"""
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询场馆排期", "params": {}},
            headers={
                "X-Execution-Context": ctx_header(context),
                "X-Mock-Scenario": "missing_context",
            },
        )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error_code"] == "AUTH_CONTEXT_MISSING"


async def test_query_mock_scenario_ignored_in_strict_mode(server_transport, monkeypatch):
    """X-Mock-Scenario 仅 DEV 档生效；STRICT 档忽略该头（审核建议 5）。"""
    monkeypatch.setattr("exhibition_agent.server.settings.execution_mode", "STRICT")
    monkeypatch.setattr("exhibition_agent.server.settings.context_jwt_secret", "test-secret-key")
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    payload = make_context_payload()
    signed = encode_jwt(payload, secret="test-secret-key")
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询展位销售率", "params": {"metric": "sales_rate"}},
            headers={
                "X-Execution-Context": signed,
                "X-Mock-Scenario": "metric_not_verified",
            },
        )
    # STRICT 档忽略 mock 头：warehouse 走 mock 默认（normal_200）路径 → 正常 200 信封
    assert resp.status_code == 200
    assert resp.json()["answer"] != "该指标待接入"


async def test_query_warehouse_scope_denied_maps_403(server_transport, monkeypatch):
    """warehouse 403 → skill return(error_code=SCOPE_DENIED) → server 按契约 §C2 映射 403。

    回归守卫（二审问题 1）：映射不得被 "result is None" 挡住——skill 对
    ScopeDeniedError 是 return 带 error_code 的 SkillResult（非 raise）。
    """
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询场馆排期", "params": {}},
            headers={
                "X-Execution-Context": ctx_header(context),
                "X-Mock-Scenario": "scope_denied",
            },
        )
    assert resp.status_code == 403, "SCOPE_DENIED 必须映射 403（不得因 result 非 None 落回 200）"
    data = resp.json()
    assert data["error_code"] == "SCOPE_DENIED"
    assert data["answer"] == "无权访问该资源"


async def test_query_knowledge_not_published_maps_404(server_transport, monkeypatch):
    """warehouse 404（knowledge_not_published）→ 平台映射 404（§C2，非 200）。"""
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    _patch_warehouse_client(monkeypatch, mock_transport)
    context = ctx()
    async with httpx.AsyncClient(transport=server_transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/query",
            json={"query": "查询知识条目", "params": {}},
            headers={
                "X-Execution-Context": ctx_header(context),
                "X-Mock-Scenario": "knowledge_not_published",
            },
        )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "KNOWLEDGE_NOT_PUBLISHED"


_OTEL_SDK_AVAILABLE = importlib.util.find_spec("opentelemetry.sdk") is not None


@pytest.mark.skipif(
    not _OTEL_SDK_AVAILABLE,
    reason="需 OTel SDK（agent-core[tracing] extra）；未装时本用例跳过，no-op 下 traceparent 恒 None",
)
async def test_query_success_response_carries_traceparent(server_transport, monkeypatch):
    """问题 2 回归守卫：注入真实 TracerProvider + InMemorySpanExporter 后，
    成功路径响应头必须回传 traceparent（no-op 环境下该断言无意义，故条件 skip）。
    """
    import agent_core.tracing as core_tracing
    from opentelemetry.sdk.trace.export import InMemorySpanExporter

    # init_observability 在 import server 时已以 no-op 完成（幂等），先重置模块态再注入 exporter
    monkeypatch.setattr(core_tracing, "_initialized", False)
    monkeypatch.setattr(core_tracing, "_enabled", False)
    monkeypatch.setattr(core_tracing, "_tracer", None)
    core_tracing.init_tracing(
        service_name="exhibition-test", enabled=True, exporter=InMemorySpanExporter()
    )
    assert core_tracing.is_tracing_enabled(), "OTel 注入失败，后续断言无意义"

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
    tp = resp.headers.get("traceparent")
    assert tp, "启用 OTel 后响应头应回传 traceparent（C4 trace 链路）"
    assert tp.startswith("00-"), f"traceparent 格式非法：{tp}"
