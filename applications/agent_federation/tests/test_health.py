"""联邦 /health：内存/PG 模式与缓存健康态可区分（issue #146）。

探针路径不建连、不加载模型：``storage`` 只读已装配的池单例，
缓存字段来自后端一次有界 ``health()``。这里直接调处理函数，
避开 ``api.server`` 导入期的鉴权中间件组合（另由 test_auth.py 覆盖）。
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:9999/v1")

from agent_core.cache import CacheHealth

from api import server


class _FakeCache:
    def __init__(self, health: CacheHealth) -> None:
        self._health = health

    async def health(self) -> CacheHealth:
        return self._health


def _patch_cache(monkeypatch, health: CacheHealth) -> None:
    import agent_runtime.cache

    monkeypatch.setattr(agent_runtime.cache, "get_cache", lambda _scope: _FakeCache(health))


def test_health_route_registered():
    assert any(getattr(route, "path", None) == "/health" for route in server.app.routes)


async def test_health_reports_memory_mode_and_disabled_cache(monkeypatch):
    monkeypatch.setattr("agent.db.get_pool", lambda: None)
    _patch_cache(
        monkeypatch,
        CacheHealth(backend="disabled", ready=True, degraded_reason=None, index=None),
    )

    payload = await server.health()

    assert payload == {
        "status": "ok",
        "storage": "memory",
        "cache_backend": "disabled",
        "cache_ready": True,
        "cache_degraded_reason": None,
    }


async def test_health_reports_postgres_and_degraded_cache(monkeypatch):
    monkeypatch.setattr("agent.db.get_pool", lambda: object())
    _patch_cache(
        monkeypatch,
        CacheHealth(
            backend="valkey",
            ready=False,
            degraded_reason="backend_unavailable: redis://:***@host:6379/0",
            index="semantic_cache_idx_x",
        ),
    )

    payload = await server.health()

    assert payload["storage"] == "postgres"
    assert payload["cache_backend"] == "valkey"
    assert payload["cache_ready"] is False
    assert "***" in payload["cache_degraded_reason"]
