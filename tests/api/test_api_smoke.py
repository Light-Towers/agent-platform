"""API 冒烟：内存模式下 /health 可用，/query SSE 全链路可跑通（无 LLM 无 DB）。"""

import json

from agent_server.main import app
from fastapi.testclient import TestClient


def test_health_memory_mode():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["storage"] == "memory"
        assert data["llm"] is False


def test_query_sse_direct_route():
    with TestClient(app) as client:
        resp = client.post("/query", json={"query": "帮我写一首诗"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line.removeprefix("data: "))
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        types = [e["type"] for e in events]
        assert "route" in types
        assert "answer" in types
        assert types[-1] == "done"
        route_event = next(e for e in events if e["type"] == "route")
        assert route_event["capability"] == "direct"


def test_import_rejected_in_memory_mode():
    with TestClient(app) as client:
        resp = client.post(
            "/import", files={"file": ("a.md", b"# hi\n\ncontent", "text/markdown")}
        )
        assert resp.status_code == 503
