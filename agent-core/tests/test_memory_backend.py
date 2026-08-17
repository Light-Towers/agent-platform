# -*- coding: utf-8 -*-
"""语义记忆后端 / embedder 选型回归测试（覆盖 refactor 审核发现的 Bug #1/#3/#4/安全-A）。"""
from __future__ import annotations

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
