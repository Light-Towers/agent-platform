"""联邦缓存门面 → 统一 Valkey 后端的委托契约（ADR-0013 C）。

不连真实 Valkey：只钉住门面把 scope/租户/KB/灰度传对，以及空答案走负缓存、
KB 版本更新走命名空间失效。后端行为本身由 agent-runtime 契约测试负责。
"""

from __future__ import annotations

import asyncio

from agent_core.cache import CacheHit


class _RecordingBackend:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return CacheHit(value={"answer": "cached"}, layer="l1")

    async def set(self, **kwargs):
        self.calls.append(("set", kwargs))

    async def set_negative(self, **kwargs):
        self.calls.append(("set_negative", kwargs))

    async def invalidate(self, **kwargs):
        self.calls.append(("invalidate", kwargs))

    async def invalidate_namespace(self, **kwargs):
        self.calls.append(("invalidate_namespace", kwargs))

    def get_stats(self):
        return {"backend": "fake"}

    def reset_stats(self):
        return None


def _install(monkeypatch):
    from agent.cache import semantic_cache as facade

    backend = _RecordingBackend()
    monkeypatch.setattr(facade, "get_cache", lambda scope: backend)
    return facade, backend


def _clean_context(monkeypatch, **env):
    from agent.cache.config import reset_cache_context

    for key in ("TENANT_ID", "KB_VERSION_WENDA", "KB_VERSION_KNOWLEDGE", "KB_VERSION_KEFU", "GRAY_PCT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    reset_cache_context()


def test_get_delegates_scope_and_request_context(monkeypatch):
    facade, backend = _install(monkeypatch)
    _clean_context(monkeypatch, TENANT_ID="tenant-a", KB_VERSION_WENDA="v9", GRAY_PCT="0.25")

    result = asyncio.run(facade.SemanticCache.get("sql", "查销售额", query_vec=[0.1, 0.2]))

    assert result == {"answer": "cached", "_layer": "l1"}
    kind, kwargs = backend.calls[0]
    assert kind == "get"
    assert kwargs["tenant_id"] == "tenant-a"
    assert kwargs["kb_versions"]["wenda"] == "v9"
    assert kwargs["gray_pct"] == 0.25
    assert kwargs["embedding"] == [0.1, 0.2]


def test_set_with_answer_uses_positive_write_and_cleans_private_fields(monkeypatch):
    facade, backend = _install(monkeypatch)
    _clean_context(monkeypatch, TENANT_ID="tenant-a")

    asyncio.run(
        facade.SemanticCache.set(
            "sql",
            "查销售额",
            {"answer": "42", "_layer": "l1", "trace_id": "t"},
        )
    )

    kind, kwargs = backend.calls[0]
    assert kind == "set"
    assert kwargs["tenant_id"] == "tenant-a"
    assert kwargs["value"]["answer"] == "42"
    assert kwargs["value"]["trace_id"] == "t"
    assert "_layer" not in kwargs["value"]
    assert "cached_at" in kwargs["value"]


def test_set_without_answer_uses_negative_cache(monkeypatch):
    facade, backend = _install(monkeypatch)
    _clean_context(monkeypatch, TENANT_ID="tenant-a")

    asyncio.run(facade.SemanticCache.set("sql", "空结果", {"answer": ""}))

    kind, kwargs = backend.calls[0]
    assert kind == "set_negative"
    assert kwargs["tenant_id"] == "tenant-a"


def test_kb_version_update_bumps_namespace_and_context(monkeypatch):
    facade, backend = _install(monkeypatch)
    _clean_context(monkeypatch, TENANT_ID="tenant-a", KB_VERSION_WENDA="v1")

    asyncio.run(facade.SemanticCache.invalidate_by_kb_version("wenda", "v2"))

    kinds = [kind for kind, _ in backend.calls]
    assert kinds == ["invalidate_namespace"]
    assert backend.calls[0][1]["tenant_id"] == "tenant-a"
    from agent.cache.config import get_cache_context

    assert get_cache_context().kb_versions["wenda"] == "v2"


def test_disabled_backend_is_a_noop(monkeypatch):
    facade, backend = _install(monkeypatch)
    backend.enabled = False
    _clean_context(monkeypatch, TENANT_ID="tenant-a")

    assert asyncio.run(facade.SemanticCache.get("sql", "q")) is None
    asyncio.run(facade.SemanticCache.set("sql", "q", {"answer": "a"}))
    assert backend.calls == []
