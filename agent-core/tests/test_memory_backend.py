# -*- coding: utf-8 -*-
"""语义记忆后端 / embedder 选型回归测试（覆盖 refactor 审核发现的 Bug #1/#3/#4/安全-A）。"""
from __future__ import annotations

import asyncio
import importlib

import pytest

import agent_core.memory as mem_pkg
from agent_core.memory.embedder import (
    MockEmbedder,
    SiliconFlowEmbedder,
    get_embedder,
)


# ── Bug #3：统一入口 re-export 完整性 ───────────────────────────────────────
def test_top_level_reexports_semantic_memory_enabled():
    assert hasattr(mem_pkg, "semantic_memory_enabled")
    assert callable(mem_pkg.semantic_memory_enabled)
    assert mem_pkg.semantic_memory_enabled() in (True, False)


def test_top_level_reexports_mock_and_localfn_embedder():
    assert hasattr(mem_pkg, "MockEmbedder")
    assert hasattr(mem_pkg, "LocalFnEmbedder")
    assert mem_pkg.MockEmbedder is MockEmbedder


# ── Bug #4：仅配 SILICONFLOW_API_KEY 必须走 SiliconFlowEmbedder(1024维) ─────
def test_get_embedder_siliconflow_key_uses_siliconflow_embedder(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODE", "auto")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-fake-key")
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    # 清掉缓存，强制按当前环境变量重建
    import agent_core.memory.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "_EMBEDDER", None)
    provider = get_embedder(force=True)
    assert isinstance(provider, SiliconFlowEmbedder)
    assert provider.dim == 1024  # bge-m3 维度，与既有向量数据一致


def test_get_embedder_remote_mode_uses_remote_embedder(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODE", "remote")
    monkeypatch.setenv("EMBEDDING_API_KEY", "rk-fake")
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    import agent_core.memory.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "_EMBEDDER", None)
    provider = get_embedder(force=True)
    assert type(provider).__name__ == "RemoteEmbedder"


def test_get_embedder_no_key_uses_mock(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODE", "auto")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    import agent_core.memory.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "_EMBEDDER", None)
    provider = get_embedder(force=True)
    assert isinstance(provider, MockEmbedder)


# ── Bug #1：PgVectorMemoryBackend.__init__ 必须设 self._dim ────────────────
def test_pgvector_backend_sets_dim_on_init(monkeypatch):
    monkeypatch.delenv("MONGO_URL", raising=False)
    from agent_core.memory.vector_backend import PgVectorMemoryBackend

    backend = PgVectorMemoryBackend(
        database_url="postgresql://fake/fake",
        collection="memories",
        tenant_id="default",
        embedder=MockEmbedder(dim=512),
    )
    # _init_schema 用到的属性必须存在
    assert backend._dim == 512
    assert backend._embedder.dim == 512


# ── 安全-A：Milvus expr 注入防护 ───────────────────────────────────────────
def test_milvus_escape_rejects_control_chars():
    from agent_core.memory.vector_backend import MilvusMemoryBackend

    with pytest.raises(ValueError):
        MilvusMemoryBackend._escape_milvus_str('bad\nuser')


def test_milvus_escape_quotes():
    from agent_core.memory.vector_backend import MilvusMemoryBackend

    out = MilvusMemoryBackend._escape_milvus_str('a"b')
    assert out == 'a\\"b'


# ── 优化 ③ #5：Milvus 异步嵌入不阻塞 / 无嵌套死锁 ───────────────────────────
class _AsyncFakeEmbedder:
    """模拟 LocalFnEmbedder：只有 aembed（无同步 embed 可用）。"""
    dim = 4

    async def aembed(self, texts):
        return [[float(i) / len(texts) for i in range(4)] for _ in texts]


class _SyncFakeEmbedder:
    """模拟 MockEmbedder：只有同步 embed（无 aembed）。"""
    dim = 4

    def embed(self, texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def test_milvus_aembed_prefers_async_embedder():
    """有 aembed 时直接 await，不调用同步 embed（避免事件循环内 asyncio.run 死锁）。"""
    from agent_core.memory.vector_backend import MilvusMemoryBackend

    backend = MilvusMemoryBackend(collection="c", tenant_id="t", embedder=_AsyncFakeEmbedder())
    vec = asyncio.run(backend._aembed("hello"))
    assert vec[:2] == [0.0, 1.0]


def test_milvus_aembed_falls_back_to_sync_via_executor():
    """无 aembed 时回退同步 embed 并经 executor（不阻塞事件循环）。"""
    import asyncio

    from agent_core.memory.vector_backend import MilvusMemoryBackend

    backend = MilvusMemoryBackend(collection="c", tenant_id="t", embedder=_SyncFakeEmbedder())
    vec = asyncio.run(backend._aembed("hello"))
    assert vec == [0.1, 0.2, 0.3, 0.4]


class _FakeMilvusColl:
    """内存版 Milvus collection：记录 search/insert 调用，不连真服务端。"""
    def __init__(self):
        self.insert_calls = []
        self.search_calls = []

    def insert(self, rows):
        self.insert_calls.append(rows)

    def search(self, *, data, anns_field, param, limit, expr, output_fields):
        self.search_calls.append({"data": data, "expr": expr, "limit": limit})
        # 返回形如 res[0] = [hit]，hit.entity.get("content")
        return [[_Hit("mem-1")]]


class _Hit:
    def __init__(self, content):
        self.entity = _Entity(content)


class _Entity:
    def __init__(self, content):
        self._c = content

    def get(self, key):
        return self._c


def test_milvus_recall_uses_async_embed_and_executor():
    """recall 应走 _aembed + executor 包裹 search，且按 tenant/user 过滤。"""
    import asyncio

    from agent_core.memory.vector_backend import MilvusMemoryBackend

    backend = MilvusMemoryBackend(collection="c", tenant_id="t", embedder=_AsyncFakeEmbedder())
    fake = _FakeMilvusColl()

    async def _run():
        # 绕过真实连接：直接注入假 collection 并 monkeypatch _connect
        backend._connect = lambda: fake
        return await backend.recall(None, "u1", "q", k=2)

    out = asyncio.run(_run())
    assert out == ["mem-1"]
    assert fake.search_calls[0]["expr"] == 'user_id == "u1" and tenant_id == "t"'
    assert fake.search_calls[0]["limit"] == 2


def test_milvus_remember_spawns_daemon_thread():
    """remember 必须后台线程异步写入，不阻塞调用方（且最终落库）。"""
    import time

    from agent_core.memory.vector_backend import MilvusMemoryBackend

    backend = MilvusMemoryBackend(collection="c", tenant_id="t", embedder=_AsyncFakeEmbedder())
    fake = _FakeMilvusColl()
    backend._connect = lambda: fake

    # 同步调用立即返回（不阻塞）
    backend.remember(None, "u1", "some memory")
    # 等后台线程完成
    deadline = time.time() + 3.0
    while not fake.insert_calls and time.time() < deadline:
        time.sleep(0.02)
    assert fake.insert_calls, "remember 后台线程应触发 insert"
    rows = fake.insert_calls[0]
    # [user_id, tenant_id, content, embedding]
    assert rows[0] == ["u1"]
    assert rows[1] == ["t"]
    assert rows[2] == ["some memory"]
