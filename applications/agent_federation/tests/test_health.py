"""联邦 /health：内存/PG 模式与缓存健康态可区分（issue #146）。

探针路径不建连、不加载模型：``storage`` 只读已装配的池单例，
缓存字段来自后端一次有界 ``health()``。这里直接调处理函数，
避开 ``api.server`` 导入期的鉴权中间件组合（另由 test_auth.py 覆盖）。
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:9999/v1")

from agent_core.cache import CacheHealth
from shared_schemas import CacheStatsReport

from api import server


class _FakeCache:
    """镜像真实后端契约：除 `health()` 外还必须有 `get_stats()`。

    `SemanticCacheBackend` Protocol 把 `get_stats()` 定为契约成员，而 /health 现在消费它。
    此前这个替身只实现了 `health()`——那是"替身只实现我以为的接口"的形状：产品代码一接
    统计面，它就 `AttributeError`。补齐成员而不是在产品代码里加 hasattr 兜底。
    """

    def __init__(self, health: CacheHealth, stats: dict | None = None) -> None:
        self._health = health
        self._stats = stats if stats is not None else {"backend": health.backend, "scope": "federation"}

    async def health(self) -> CacheHealth:
        return self._health

    def get_stats(self) -> dict:
        return dict(self._stats)


def _patch_cache(monkeypatch, health: CacheHealth, stats: dict | None = None) -> None:
    import agent_runtime.cache

    monkeypatch.setattr(agent_runtime.cache, "get_cache", lambda _scope: _FakeCache(health, stats))


def test_health_route_registered():
    assert any(getattr(route, "path", None) == "/health" for route in server.app.routes)


async def test_health_reports_memory_mode_and_disabled_cache(monkeypatch):
    monkeypatch.setattr("agent.db.get_pool", lambda: None)
    _patch_cache(
        monkeypatch,
        CacheHealth(backend="disabled", ready=True, degraded_reason=None, index=None),
    )

    payload = await server.health()

    # 既有五个键的等值判据原样保留，只把新增的 cache_stats 单独按形状判——
    # 这不是放宽：少一个键、多一个键都照样红（键集合由下面那条钉死）。
    assert {k: v for k, v in payload.items() if k != "cache_stats"} == {
        "status": "ok",
        "storage": "memory",
        "cache_backend": "disabled",
        "cache_ready": True,
        "cache_degraded_reason": None,
    }
    assert set(payload["cache_stats"]) == set(CacheStatsReport.model_fields), "探针面的键集合必须恒等于契约形状"
    assert payload["cache_stats"]["backend"] == "disabled" and payload["cache_stats"]["total"] == 0


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
        # 后端报了计数 ⇒ 探针面必须带出去（缺的键由契约模型补 0，形状仍全量）
        {"backend": "valkey", "scope": "federation", "total": 6, "l2_hit": 2, "hit_rate": 0.3333, "dropped_writes": 1},
    )

    payload = await server.health()

    assert payload["storage"] == "postgres"
    assert payload["cache_backend"] == "valkey"
    assert payload["cache_ready"] is False
    assert set(payload["cache_stats"]) == set(CacheStatsReport.model_fields)
    assert payload["cache_stats"]["hit_rate"] == 0.3333 and payload["cache_stats"]["dropped_writes"] == 1
    assert payload["cache_stats"]["miss"] == 0, "未上报的计数渲成 0，而不是键消失"
    assert "***" in payload["cache_degraded_reason"]
