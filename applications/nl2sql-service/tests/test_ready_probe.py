# -*- coding: utf-8 -*-
"""/ready 探池与启动入口用例（2026-10-18，Q26 落地方案）。

钉四件事：
1. fake pools 注入 app.state → /ready 健康 200；
2. 池缺失 / 探活失败 → 503（k8s readinessProbe 据此切流量）；
3. /health 仍是原共享契约（dependencies == []）——/ready 不许并进 /health；
4. console script `nl2sql-service` 指向 server:main，且 main 用
   Settings.host/port 起 uvicorn（此前指向空壳构建 CLI，Q26②）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nl2sql_service.api.server import create_app, main


class _OkConn:
    async def __aenter__(self) -> "_OkConn":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, sql: str) -> None:
        assert sql == "SELECT 1", f"探活语句漂移: {sql}"


class _OkPool:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def connection(self, timeout: float | None = None) -> _OkConn:
        self.timeouts.append(timeout)
        return _OkConn()


class _DeadPool:
    def connection(self, timeout: float | None = None) -> _OkConn:
        raise RuntimeError("pool is closed")


def test_ready_returns_healthy_when_both_pools_probe_ok():
    app = create_app()
    app.state.pools = {"meta": _OkPool(), "dw": _OkPool()}

    r = TestClient(app).get("/ready")

    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert r.json()["pools"] == {"meta": "ok", "dw": "ok"}


def test_ready_uses_short_probe_timeout():
    meta = _OkPool()
    app = create_app()
    app.state.pools = {"meta": meta, "dw": _OkPool()}

    TestClient(app).get("/ready")

    assert meta.timeouts and meta.timeouts[0] is not None
    assert meta.timeouts[0] <= 5, "就绪探针必须是短超时（dw 语句超时是 30s，等不起）"


def test_ready_returns_503_when_a_pool_is_missing():
    app = create_app()
    app.state.pools = {"meta": _OkPool()}  # dw 未登记（DSN 未配置或 lifespan 未跑）

    r = TestClient(app).get("/ready")

    assert r.status_code == 503
    assert r.json()["detail"]["pools"]["dw"] == "pool not registered"


def test_ready_returns_503_when_probe_fails():
    app = create_app()
    app.state.pools = {"meta": _OkPool(), "dw": _DeadPool()}

    r = TestClient(app).get("/ready")

    assert r.status_code == 503
    assert r.json()["detail"]["pools"]["dw"] == "RuntimeError"


def test_ready_returns_503_without_pools_registered():
    r = TestClient(create_app()).get("/ready")

    assert r.status_code == 503, "未初始化（lifespan 未跑）的实例不是 ready"


def test_health_route_still_on_shared_contract():
    body = TestClient(create_app()).get("/health").json()

    assert body["status"] == "healthy"
    assert body["version"] == "0.1.0"
    assert body["dependencies"] == [], "/health 是共享契约，不许并进池状态"


def test_console_script_points_to_server_main():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert data["project"]["scripts"]["nl2sql-service"] == "nl2sql_service.api.server:main"


def test_main_starts_uvicorn_with_settings_host_port(monkeypatch):
    """main 必须用 Settings.host/port 起 uvicorn（不写死、不读 env 另起一套）。

    注：`get_settings()` 里 app_config.yaml 的 `server` 段恒定覆盖 env（既有
    语义），所以这里直接 patch get_settings，测的是 main 的接线而非配置源。
    """
    captured: dict[str, object] = {}

    def _fake_run(app: object, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    class _Settings:
        host = "127.0.0.1"
        port = 9180

    monkeypatch.setattr("uvicorn.run", _fake_run)
    monkeypatch.setattr("nl2sql_service.conf.settings.get_settings", lambda: _Settings())

    main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9180
    assert isinstance(captured["app"], FastAPI)
