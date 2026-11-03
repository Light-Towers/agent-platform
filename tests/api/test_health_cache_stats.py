"""/health 的缓存命中率出口（ADR-0013 Stage 4 判据「命中率可在指标或 health 读到」）。

此前 `get_stats()` 在 agent_server 零消费方：纯 miss 负载下命中率没有任何可读面，
而 `/health` 只报 backend/ready/degraded_reason 三盏灯——"缓存装了但一直没命中"与
"缓存根本没在被调用"在现网读起来一模一样。本批把它接进探针面，并钉住两条形状判据：

1. **输入变则值变**（不是装配态代理）：后端计数变 ⇒ `/health` 的 `cache_stats` 跟着变；
2. **键集合恒定**：真实 disabled 后端与"有计数"的后端产出的键完全一致——
   缺的计数渲成 0，于是"没发生"与"没上报"在监控面上第一次可区分。

探针路径红线同 `health_router` 里既有的两条：这里只做纯内存读（`get_stats()` 不发命令、
不加载 embedder），所以不因接统计而给 readiness 增加延迟。
"""

from __future__ import annotations

import pytest
from agent_core.cache import CacheHealth
from agent_server.main import app
from fastapi.testclient import TestClient
from shared_schemas import CacheStatsReport

_FULL_KEYS = set(CacheStatsReport.model_fields)


class _StubBackend:
    enabled = True

    def __init__(self, stats: dict) -> None:
        self._stats = stats

    async def health(self) -> CacheHealth:
        return CacheHealth(backend=self._stats.get("backend", "valkey"), ready=True, degraded_reason=None, index=None)

    def get_stats(self) -> dict:
        return dict(self._stats)


def _install(monkeypatch, stats: dict) -> None:
    monkeypatch.setattr("agent_runtime.cache.get_cache", lambda scope: _StubBackend(stats))


def _get_health() -> dict:
    with TestClient(app) as client:
        return client.get("/health").json()


def test_cache_stats_counts_surface_and_move_with_input(monkeypatch):
    """输入变则值变：后端计数是这份读数的唯一来源，不是配置意愿的复述。"""
    _install(monkeypatch, {"backend": "valkey", "scope": "agent_server", "total": 4, "l1_hit": 3, "hit_rate": 0.75})
    first = _get_health()["cache_stats"]
    assert first["total"] == 4 and first["l1_hit"] == 3 and first["hit_rate"] == 0.75

    _install(monkeypatch, {"backend": "valkey", "scope": "agent_server", "total": 8, "l2_hit": 5, "hit_rate": 0.625})
    second = _get_health()["cache_stats"]
    assert second["total"] == 8 and second["l2_hit"] == 5, "换一个后端读数必须变，否则这条灯是装配态代理"
    assert first != second


def test_cache_stats_key_set_is_constant_across_backends(monkeypatch):
    """键集合恒定：稀疏计数（只有 backend/scope）也必须渲成全量 16 键。"""
    _install(monkeypatch, {"backend": "valkey", "scope": "agent_server"})
    sparse = _get_health()["cache_stats"]
    assert set(sparse) == _FULL_KEYS
    assert sparse["total"] == 0 and sparse["hit_rate"] == 0.0 and sparse["dropped_writes"] == 0

    _install(
        monkeypatch,
        {
            "backend": "valkey",
            "scope": "agent_server",
            "total": 2,
            "miss": 2,
            "hit_rate": 0.0,
            "dropped_writes": 1,
        },
    )
    warm = _get_health()["cache_stats"]
    assert set(warm) == _FULL_KEYS, "两个读法键集合必须一致，否则'没发生'与'没上报'又同形"
    assert warm["dropped_writes"] == 1 and warm["miss"] == 2


def test_real_disabled_backend_health_shape_is_complete():
    """无替身的一条：根套件默认 CACHE_BACKEND=disabled，真实后端的读数同样全量键。

    这条刻意不装替身——它证的是"disabled 后端 + 契约模型"这条真实组合的形状，
    上面两条只证到调用形状。
    """
    payload = _get_health()
    assert payload["cache_backend"] == "disabled", payload["cache_backend"]
    stats = payload["cache_stats"]
    assert set(stats) == _FULL_KEYS
    assert stats["backend"] == "disabled" and stats["scope"] == "agent_server"


def test_health_still_200_when_backend_reports_unknown_counter(monkeypatch):
    """探针面 fail-open：后端将来加计数器不许把 readiness 打成 500。"""
    _install(monkeypatch, {"backend": "valkey", "scope": "agent_server", "brand_new_counter": 1, "total": 1})
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert set(resp.json()["cache_stats"]) == _FULL_KEYS


@pytest.mark.parametrize("key", sorted(_FULL_KEYS))
def test_every_contract_field_appears_in_health_payload(key, monkeypatch):
    """逐字段在场（参数化到每个键，漏一个就报具体那一个而不是整块 diff）。"""
    _install(monkeypatch, {"backend": "valkey", "scope": "agent_server"})
    assert key in _get_health()["cache_stats"]
