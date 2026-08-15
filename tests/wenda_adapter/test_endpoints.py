"""测试 wenda-adapter /query 和 /health 端点。"""

import httpx
from fastapi.testclient import TestClient


def _make_mock_client(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(timeout=httpx.Timeout(10.0), transport=transport)


def test_query_empty_body():
    from main import app

    with TestClient(app) as tc:
        resp = tc.post("/query", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == ""
        assert body["latency_ms"] == 0.0


def test_query_upstream_200():
    import main

    json_body = {"answer": "42", "latency_ms": 5.0}
    mock = _make_mock_client(lambda req: httpx.Response(200, json=json_body))

    with TestClient(main.app) as tc:
        main._client = mock
        resp = tc.post("/query", json={"query": "select 1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "42"
        assert body["fallback"] is False


def test_query_upstream_500():
    import main

    mock = _make_mock_client(lambda req: httpx.Response(500, text="err"))

    with TestClient(main.app) as tc:
        main._client = mock
        resp = tc.post("/query", json={"query": "select 1"})
        assert resp.status_code == 200
        body = resp.json()
        assert "非 200" in body["answer"]
        assert body["fallback"] is True


def test_query_connect_error():
    import main

    def handler(req):
        raise httpx.ConnectError("connection refused")

    mock = _make_mock_client(handler)

    with TestClient(main.app) as tc:
        main._client = mock
        resp = tc.post("/query", json={"query": "select 1"})
        assert resp.status_code == 200
        body = resp.json()
        assert "不可达" in body["answer"]
        assert body["fallback"] is True


def test_query_json_error():
    import main

    json_body = {"answer": "", "error": "upstream boom"}
    mock = _make_mock_client(lambda req: httpx.Response(200, json=json_body))

    with TestClient(main.app) as tc:
        main._client = mock
        resp = tc.post("/query", json={"query": "select 1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["fallback"] is True


def test_health_healthy():
    import main

    mock = _make_mock_client(lambda req: httpx.Response(200, text="ok"))

    with TestClient(main.app) as tc:
        main._client = mock
        resp = tc.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert len(body["dependencies"]) == 1
        assert body["dependencies"][0]["name"] == "wenda"


def test_health_unhealthy():
    import main

    def handler(req):
        raise httpx.ConnectError("down")

    mock = _make_mock_client(handler)

    with TestClient(main.app) as tc:
        main._client = mock
        resp = tc.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unhealthy"
