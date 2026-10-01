# -*- coding: utf-8 -*-
"""WS-1：统一记忆存储门面 MemoryStore 单测（框架无关，无 DB 无 LLM）。

验证：
- PgMemoryStore 五动词委托 typed 模块（fake psycopg 池）；
- 失败隔离：pool/embed 异常 → 降级空结果，绝不向上抛；
- CapabilityReport 探测语义（enabled/backend/supports_*）；
- VectorMemoryStore 委托 MemoryBackend，consolidate/forget 如实不支持；
- semantic.reset_backend_cache 清空 lru_cache。
"""

from __future__ import annotations

import pytest

from agent_core.memory.store import (
    CapabilityReport,
    MemoryStore,
    PgMemoryStore,
    VectorMemoryStore,
)


# --- fake psycopg 池（与 test_typed_memory.py 同款）--------------------------

class _FakeCur:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows=None, rowcount=0):
        self._cur = _FakeCur(rows, rowcount)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return self._cur

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _FakePool:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows
        self._rowcount = rowcount
        self.executed: list[tuple] = []

    def connection(self):
        conn = _FakeConn(self._rows, self._rowcount)
        self.executed.append(("connection",))
        return conn


def _embed_fn(text: str) -> list[float]:
    return [0.1, 0.2, 0.3]


# --- PgMemoryStore -----------------------------------------------------------

@pytest.mark.asyncio
async def test_pg_store_recall_delegates_typed():
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    rows = [
        ("事实A", "semantic", 0.9, now),
        ("事实B", "episodic", 0.2, now),
    ]
    pool = _FakePool(rows=rows)
    store = PgMemoryStore(pool, _embed_fn)
    out = await store.recall("ws1", "任意问题", k=2, tenant_id="default")
    assert set(out) == {"事实A", "事实B"}


@pytest.mark.asyncio
async def test_pg_store_threads_tenant_id_to_typed(monkeypatch):
    """门面必须把 tenant_id 透传到内核 typed 五动词（漏传即读写共享 default 桶）。"""
    import agent_core.memory.typed as typed_mod

    captured: dict = {}

    async def _fake_recall_typed(pool, *, user_id, question, k, weights, embedding, tenant_id):
        captured["recall"] = tenant_id
        return []

    async def _fake_remember_typed(pool, *, user_id, fact, memory_type, importance, embedding, tenant_id):
        captured["remember"] = tenant_id

    async def _fake_consolidate(user_id, pool, *, forget_threshold, age_days, tenant_id):
        captured["consolidate"] = tenant_id
        return 0

    async def _fake_forget(user_id, pool, memory_id, *, tenant_id):
        captured["forget"] = tenant_id
        return True

    monkeypatch.setattr(typed_mod, "recall_typed", _fake_recall_typed)
    monkeypatch.setattr(typed_mod, "remember_typed", _fake_remember_typed)
    monkeypatch.setattr(typed_mod, "consolidate", _fake_consolidate)
    monkeypatch.setattr(typed_mod, "forget", _fake_forget)

    store = PgMemoryStore(_FakePool(), _embed_fn)
    await store.recall("ws1", "q", tenant_id="tenantA")
    await store.remember("ws1", "事实", tenant_id="tenantA")
    await store.consolidate("ws1", tenant_id="tenantA")
    await store.forget("ws1", 1, tenant_id="tenantA")
    assert captured == {
        "recall": "tenantA",
        "remember": "tenantA",
        "consolidate": "tenantA",
        "forget": "tenantA",
    }
    # 缺省仍为 default（向后兼容），但宿主必须显式传入才能隔离
    captured.clear()
    await store.recall("ws1", "q", tenant_id="default")
    assert captured == {"recall": "default"}


@pytest.mark.asyncio
async def test_pg_store_recall_empty_on_no_pool_or_blank_input():
    store = PgMemoryStore(None, _embed_fn)
    assert await store.recall("ws1", "q", tenant_id="default") == []
    store2 = PgMemoryStore(_FakePool(), _embed_fn)
    assert await store2.recall("", "q", tenant_id="default") == []
    assert await store2.recall("ws1", "", tenant_id="default") == []


@pytest.mark.asyncio
async def test_pg_store_recall_failure_isolates():
    class _BoomPool:
        def connection(self):
            raise RuntimeError("db down")

    store = PgMemoryStore(_BoomPool(), _embed_fn)
    assert await store.recall("ws1", "q", tenant_id="default") == []  # 绝不向上抛


@pytest.mark.asyncio
async def test_pg_store_remember_writes_via_typed():
    pool = _FakePool(rowcount=1)
    store = PgMemoryStore(pool, _embed_fn)
    await store.remember("ws1", "一条记忆", memory_type="semantic", importance=0.8, tenant_id="default")


@pytest.mark.asyncio
async def test_pg_store_remember_supports_async_embed_fn():
    async def _aembed(text: str) -> list[float]:
        return [0.5, 0.5]

    pool = _FakePool(rowcount=1)
    store = PgMemoryStore(pool, _aembed)
    await store.remember("ws1", "异步嵌入记忆", tenant_id="default")


@pytest.mark.asyncio
async def test_pg_store_consolidate_returns_deleted():
    pool = _FakePool(rowcount=3)
    store = PgMemoryStore(pool, _embed_fn)
    assert await store.consolidate("ws1", forget_threshold=0.1, age_days=30, tenant_id="default") == 3


@pytest.mark.asyncio
async def test_pg_store_forget_bool():
    pool = _FakePool(rowcount=1)
    store = PgMemoryStore(pool, _embed_fn)
    assert await store.forget("ws1", 42, tenant_id="default") is True
    pool0 = _FakePool(rowcount=0)
    assert await PgMemoryStore(pool0, _embed_fn).forget("ws1", 99, tenant_id="default") is False


def test_pg_store_probe_full_capabilities():
    report = PgMemoryStore(_FakePool(), _embed_fn).probe()
    assert report.enabled is True
    assert report.backend == "pg-typed"
    assert report.embedder_source == "injected"
    assert report.supports_consolidate is True
    assert report.supports_forget is True
    assert report.supports_tenant_isolation is True  # typed SQL 按 tenant_id 精确过滤
    assert report.as_dict()["backend"] == "pg-typed"


def test_pg_store_probe_disabled_without_pool():
    report = PgMemoryStore(None, _embed_fn).probe()
    assert report.enabled is False
    assert report.reason != ""


# --- VectorMemoryStore ---------------------------------------------------------

class _FakeBackend:
    def __init__(self):
        self.recalls: list[tuple] = []
        self.remembers: list[tuple] = []

    async def recall(self, pool, user_id, question, k=3):
        self.recalls.append((user_id, question, k))
        return ["m1", "m2"]

    def remember(self, pool, user_id, content):
        self.remembers.append((user_id, content))


@pytest.mark.asyncio
async def test_vector_store_delegates_backend():
    backend = _FakeBackend()
    store = VectorMemoryStore(backend)
    assert await store.recall("u1", "q", k=2, tenant_id="default") == ["m1", "m2"]
    await store.remember("u1", "内容", tenant_id="default")
    assert backend.remembers == [("u1", "内容")]
    # 向量后端不支持巩固/遗忘，如实返回
    assert await store.consolidate("u1", tenant_id="default") == 0
    assert await store.forget("u1", 1, tenant_id="default") is False


@pytest.mark.asyncio
async def test_vector_store_failure_isolates():
    class _BoomBackend:
        async def recall(self, pool, user_id, question, k=3):
            raise RuntimeError("milvus down")

        def remember(self, pool, user_id, content):
            raise RuntimeError("milvus down")

    store = VectorMemoryStore(_BoomBackend())
    assert await store.recall("u1", "q", tenant_id="default") == []
    await store.remember("u1", "c", tenant_id="default")  # 不抛


def test_vector_store_probe():
    report = VectorMemoryStore(_FakeBackend()).probe()
    assert report.enabled is True
    assert report.backend == "_FakeBackend"
    assert report.embedder_source == "backend-internal"
    assert report.supports_consolidate is False
    assert report.supports_tenant_isolation is False  # 后端无 tenant 列，tenant_id 被忽略
    assert VectorMemoryStore(None).probe().enabled is False


def test_store_protocol_runtime_checkable():
    assert isinstance(PgMemoryStore(_FakePool(), _embed_fn), MemoryStore)
    assert isinstance(VectorMemoryStore(_FakeBackend()), MemoryStore)
    assert isinstance(CapabilityReport(enabled=True, backend="x"), CapabilityReport)


# --- semantic 门面缓存复位 ------------------------------------------------------

def test_reset_backend_cache_clears_lru(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "false")
    from agent_core.memory import semantic

    semantic.reset_backend_cache()
    assert semantic.get_default_backend() is None
    # 开启后必须 reset 才能重新解析（lru_cache 固化了 None）
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "true")
    monkeypatch.setenv("VECTOR_BACKEND", "pg")
    monkeypatch.setenv("DEEPAGENTS_DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "")
    semantic.reset_backend_cache()
    # pg 后端无 database_url → 初始化失败降级 None（不抛异常）
    assert semantic.get_default_backend() is None
    semantic.reset_backend_cache()
