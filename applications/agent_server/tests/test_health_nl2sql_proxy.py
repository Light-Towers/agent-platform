# -*- coding: utf-8 -*-
"""/health/nl2sql 代理端点单测：聚合真值 + 失败降级（2026-11-20）。"""
from __future__ import annotations

import pytest
from agent_server.api.health_router import health_nl2sql, router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _Client:
    def __init__(self, responses, raises=None):
        self._responses = responses
        self._raises = raises
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if self._raises:
            raise self._raises
        return _Resp(self._responses.get(url, {}))


def _patch(monkeypatch, settings_url, client):
    from agent_server.api import health_router as hr

    class S:
        nl2sql_service_url = settings_url
    monkeypatch.setattr(hr, "get_settings", lambda: S())
    # httpx 在函数内 import，patch 全局模块的 AsyncClient
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)


@pytest.mark.asyncio
async def test_aggregates_real_truth(monkeypatch):
    c = _Client({
        "http://ns:8000/health": {"status": "healthy", "sql_backend": "postgres"},
        "http://ns:8000/ready": {"status": "healthy", "pools": {"meta": "ok", "dw": "ok"}},
    })
    _patch(monkeypatch, "http://ns:8000/", c)
    r = await health_nl2sql()
    assert r["ok"] is True
    assert r["sql_backend"] == "postgres"
    assert r["pools"] == {"meta": "ok", "dw": "ok"}
    assert c.calls == ["http://ns:8000/health", "http://ns:8000/ready"]


@pytest.mark.asyncio
async def test_down_pool_marks_unavailable(monkeypatch):
    c = _Client({
        "http://ns:8000/health": {"status": "healthy", "sql_backend": "postgres"},
        "http://ns:8000/ready": {"status": "healthy", "pools": {"meta": "ok", "dw": "error"}},
    })
    _patch(monkeypatch, "http://ns:8000/", c)
    r = await health_nl2sql()
    assert r["ok"] is False


@pytest.mark.asyncio
async def test_unconfigured_degrades(monkeypatch):
    _patch(monkeypatch, "", _Client({}))
    r = await health_nl2sql()
    assert r["ok"] is False and "未配置" in r["error"]


@pytest.mark.asyncio
async def test_network_error_degrades(monkeypatch):
    c = _Client({}, raises=ConnectionError("boom"))
    _patch(monkeypatch, "http://ns:8000/", c)
    r = await health_nl2sql()
    assert r["ok"] is False and "ConnectionError" in r["error"]

