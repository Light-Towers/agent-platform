# -*- coding: utf-8 -*-
"""文档检索后端（DocumentStore 协议 + 工厂）契约测试。

钉四件事（方案 plan-knowledge-base-model-2026-11-17 步骤 1）：
1. **协议符合性**：两个实现都能过 ``runtime_checkable`` 的 isinstance 检查——
   消费方依赖接口，后端可切换的前提是两边真的同形。
2. **工厂行为**：DOC_BACKEND 三种取值的装配结果；milvus 缺 URI 返回 None
   （可读降级，不抛）；未知值 ValueError（配置写错当场暴露）。
3. **Milvus 过滤表达式**：tenant 严格谓词 + workspace/knowledge 可选子句 +
   字符串转义（KS 语义：转义不是拒绝，因为集合由 KS 原样写值）。
4. **检索映射**：hybrid_search 命中（dict hit）→ [{id, source, heading, content,
   score}]，与 pgvector 后端同形状；knowledge_id 端到端透传进过滤表达式。

pymilvus 以假模块替身注入（懒加载在 _connect 才 import，不打真连接）。
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agent_runtime.document_store import (
    DocumentChunk,
    DocumentStore,
    DocumentStoreUnavailable,
    MilvusDocumentStore,
)
from agent_server.rag.backend import create_document_store, get_document_store
from agent_server.rag.pg_backend import PgVectorDocumentStore


# ---------------------------------------------------------------------------
# 假 pymilvus / 假客户端（不打网络；_connect 懒加载后才 import）
# ---------------------------------------------------------------------------
class _FakeSchema:
    def __init__(self):
        self.fields: list[dict] = []

    def add_field(self, **kw):
        self.fields.append(kw)


class _FakeIndexParams:
    def __init__(self):
        self.indexes: list[dict] = []

    def add_index(self, **kw):
        self.indexes.append(kw)


class _FakeMilvusClient:
    """记录调用的假客户端；has_collection 决定是否走建集合路径。"""

    def __init__(self, exists: bool = True, hits: list[dict] | None = None):
        self.exists = exists
        self.hits = hits or []
        self.calls: list[tuple] = []
        self.last_schema = None

    def has_collection(self, **kw):
        return self.exists

    def create_schema(self, **kw):
        return _FakeSchema()

    def prepare_index_params(self):
        return _FakeIndexParams()

    def create_collection(self, **kw):
        self.calls.append(("create_collection", kw))
        self.last_schema = kw.get("schema")

    def insert(self, **kw):
        self.calls.append(("insert", kw))

    def delete(self, **kw):
        self.calls.append(("delete", kw))
        return SimpleNamespace(delete_count=1)

    def hybrid_search(self, **kw):
        self.calls.append(("hybrid_search", kw))
        return [self.hits]


def _install_fake_pymilvus(monkeypatch, client: _FakeMilvusClient) -> None:
    fake = types.ModuleType("pymilvus")
    fake.MilvusClient = lambda **kw: client
    fake.DataType = SimpleNamespace(
        INT64="INT64", INT8="INT8", VARCHAR="VARCHAR",
        SPARSE_FLOAT_VECTOR="SPARSE_FLOAT_VECTOR", FLOAT_VECTOR="FLOAT_VECTOR",
    )
    fake.AnnSearchRequest = lambda **kw: SimpleNamespace(**kw)
    fake.WeightedRanker = lambda *a, **k: ("WeightedRanker", a)
    monkeypatch.setitem(sys.modules, "pymilvus", fake)


class _FakeEmbedder:
    dim = 4

    def embed(self, texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _make_store(client: _FakeMilvusClient, monkeypatch, **kw) -> MilvusDocumentStore:
    _install_fake_pymilvus(monkeypatch, client)
    return MilvusDocumentStore(uri="http://fake:19530", embedder=_FakeEmbedder(), **kw)


# ---------------------------------------------------------------------------
# 1. 协议符合性
# ---------------------------------------------------------------------------
def test_backends_satisfy_document_store_protocol():
    for backend in (PgVectorDocumentStore(), object.__new__(MilvusDocumentStore)):
        assert isinstance(backend, DocumentStore), (
            f"{type(backend).__name__} 不满足 DocumentStore 协议：消费方依赖的是接口，"
            "实现漂移（改签名/改方法名）必须在这里红"
        )


# ---------------------------------------------------------------------------
# 2. 工厂行为
# ---------------------------------------------------------------------------
def _doc_settings(**over):
    base = dict(
        doc_backend="pgvector",
        doc_milvus_uri="",
        doc_milvus_token="",
        doc_milvus_collection="platform_doc_v2_bge_m3",
        doc_embed_api_key="test-key",
        doc_embed_base_url="https://fake/v1",
        doc_embed_model="BAAI/bge-m3",
        doc_embed_dim=1024,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_factory_pgvector_builds_pg_backend():
    with patch("agent_server.rag.backend.get_settings", return_value=_doc_settings()):
        assert isinstance(create_document_store("pgvector"), PgVectorDocumentStore)


def test_factory_milvus_without_uri_returns_none_not_raise():
    """DOC_BACKEND=milvus 但 URI 未配置 → None（调用方可读降级），不抛不 500。"""
    with patch("agent_server.rag.backend.get_settings", return_value=_doc_settings()):
        assert create_document_store("milvus") is None


def test_factory_milvus_with_uri_builds_milvus_backend():
    with patch(
        "agent_server.rag.backend.get_settings",
        return_value=_doc_settings(doc_milvus_uri="http://fake:19530"),
    ):
        store = create_document_store("milvus")
    assert isinstance(store, MilvusDocumentStore)


def test_factory_unknown_mode_raises():
    with patch("agent_server.rag.backend.get_settings", return_value=_doc_settings()):
        with pytest.raises(ValueError, match="DOC_BACKEND"):
            create_document_store("redis")


def test_get_document_store_reads_current_config():
    """每次现取配置（不缓存实例）：测试/运维切 DOC_BACKEND 立即生效。"""
    with patch(
        "agent_server.rag.backend.get_settings",
        return_value=_doc_settings(doc_backend="pgvector"),
    ):
        assert isinstance(get_document_store(), PgVectorDocumentStore)
    with patch(
        "agent_server.rag.backend.get_settings",
        return_value=_doc_settings(doc_backend="milvus", doc_milvus_uri=""),
    ):
        assert get_document_store() is None  # milvus 缺 URI → None（可读降级）


# ---------------------------------------------------------------------------
# 3. Milvus 过滤表达式
# ---------------------------------------------------------------------------
def test_milvus_filter_tenant_only_when_no_scope():
    expr = MilvusDocumentStore._build_filter("tenantA", "default", "")
    assert expr == 'tenant_id == "tenantA" and workspace_id == "default"'


def test_milvus_filter_knowledge_clause_only_when_scoped():
    """knowledge_id 空 = 全部知识库（老数据未分库也可召回）；选库才加子句。"""
    unscoped = MilvusDocumentStore._build_filter("t", "ws", "")
    assert "knowledge_id" not in unscoped
    scoped = MilvusDocumentStore._build_filter("t", "ws", "kb-1")
    assert scoped.endswith('and knowledge_id == "kb-1"')


def test_milvus_filter_escapes_string_literals():
    expr = MilvusDocumentStore._build_filter('ten"ant\\X', "ws", "kb")
    assert '\\"' in expr and "\\\\" in expr  # 引号与反斜杠都转义，不破表达式结构


# ---------------------------------------------------------------------------
# 4. 检索映射与 schema 镜像
# ---------------------------------------------------------------------------
async def test_milvus_retrieve_maps_hits_to_common_shape(monkeypatch):
    client = _FakeMilvusClient(
        exists=True,
        hits=[
            {"id": 7, "distance": 0.87, "entity": {"content": "正文A", "title": "标题A", "source_doc": "file.md"}},
            {"id": 8, "distance": 0.42, "entity": {"content": "正文B", "title": "", "file_title": "file2.md"}},
        ],
    )
    store = _make_store(client, monkeypatch)

    rows = await store.retrieve(None, "问题", 5, "default", tenant_id="tenantA", knowledge_id="kb-1")

    assert [r["id"] for r in rows] == [7, 8]
    assert rows[0] == {"id": 7, "source": "file.md", "heading": "标题A", "content": "正文A", "score": 0.87}
    assert rows[1]["source"] == "file2.md" and rows[1]["heading"] == ""
    # knowledge_id 一路透传进 hybrid_search 的过滤表达式
    search_kw = client.calls[0][1]
    assert 'knowledge_id == "kb-1"' in search_kw["reqs"][0].expr
    assert 'tenant_id == "tenantA"' in search_kw["reqs"][0].expr


async def test_milvus_create_collection_mirrors_ks_schema(monkeypatch):
    """schema 逐字段镜像 KS create_collection + v2 增量（knowledge_id/workspace_id）。

    两侧字段不同步时，写入方（KS 管线）与检索方（本类）会在同一集合上互相踩。
    """
    client = _FakeMilvusClient(exists=False)
    store = _make_store(client, monkeypatch)

    await asyncio_to_thread_connect(store)

    fields = {f["field_name"] for f in client.last_schema.fields}
    for name in (
        "chunk_id", "content", "title", "parent_title", "part", "file_title",
        "item_name", "tenant_id", "scope_type", "knowledge_id", "workspace_id",
        "embedding_model", "chunk_version", "created_at", "source_doc",
        "sparse_vector", "dense_vector",
    ):
        assert name in fields, f"Milvus 集合缺字段 {name}：与 KS create_collection 镜像失步"


async def asyncio_to_thread_connect(store: MilvusDocumentStore):
    import asyncio

    await asyncio.to_thread(store._connect)


async def test_milvus_add_document_writes_scope_and_dynamic_doc_id(monkeypatch):
    client = _FakeMilvusClient(exists=True)
    store = _make_store(client, monkeypatch)

    doc_id = await store.add_document(
        None, "file.md", [DocumentChunk(text="正文", heading="标题")],
        "ws1", tenant_id="tenantA", knowledge_id="kb-9",
    )

    assert doc_id
    (_, kw), = [c for c in client.calls if c[0] == "insert"]
    row = kw["data"][0]
    assert row["tenant_id"] == "tenantA"
    assert row["knowledge_id"] == "kb-9"
    assert row["workspace_id"] == "ws1"
    assert row["doc_id"] == doc_id  # 动态字段：delete_document 对称删除的依据
    assert "sparse_vector" in row and "dense_vector" in row


async def test_milvus_delete_scopes_by_tenant_and_doc_id(monkeypatch):
    client = _FakeMilvusClient(exists=True)
    store = _make_store(client, monkeypatch)

    await store.delete_document(None, "doc123", "ws1", tenant_id="tenantA")

    (_, kw), = [c for c in client.calls if c[0] == "delete"]
    assert 'tenant_id == "tenantA"' in kw["filter"]
    assert 'doc_id == "doc123"' in kw["filter"]


# ---------------------------------------------------------------------------
# 5. pgvector 后端
# ---------------------------------------------------------------------------
async def test_pg_backend_pool_none_raises_unavailable():
    """pool None ≠ 空结果：抛 DocumentStoreUnavailable，调用方降级「知识库未启用」。"""
    backend = PgVectorDocumentStore()
    with pytest.raises(DocumentStoreUnavailable):
        await backend.retrieve(None, "q", 5, "default", tenant_id="t")


async def test_pg_backend_forwards_knowledge_id_to_store(monkeypatch):
    captured: dict = {}

    async def _fake_scoped(pool, query, top_k, workspace_id, *, tenant_id, knowledge_id=""):
        captured.update(tenant_id=tenant_id, knowledge_id=knowledge_id, workspace_id=workspace_id)
        return [{"id": 1, "source": "s", "heading": "", "content": "c", "score": 0.5}]

    with patch("agent_server.rag.pg_backend.retrieve_chunks_scoped", side_effect=_fake_scoped):
        backend = PgVectorDocumentStore()
        rows = await backend.retrieve(
            object(), "q", 5, "ws1", tenant_id="tenantA", knowledge_id="kb-3"
        )

    assert rows[0]["content"] == "c"
    assert captured == {"tenant_id": "tenantA", "knowledge_id": "kb-3", "workspace_id": "ws1"}


async def test_pg_backend_add_document_forwards_knowledge_id(monkeypatch):
    captured: dict = {}

    async def _fake_add(pool, source, chunks, workspace_id, *, tenant_id, knowledge_id=""):
        captured.update(knowledge_id=knowledge_id, workspace_id=workspace_id)
        return "docid1"

    with patch("agent_server.rag.store.add_document", side_effect=_fake_add):
        backend = PgVectorDocumentStore()
        doc_id = await backend.add_document(
            object(), "a.md", [DocumentChunk(text="x")], "ws1",
            tenant_id="tenantA", knowledge_id="kb-3",
        )

    assert doc_id == "docid1"
    assert captured == {"knowledge_id": "kb-3", "workspace_id": "ws1"}


async def test_pg_backend_add_document_pool_none_raises():
    backend = PgVectorDocumentStore()
    with pytest.raises(DocumentStoreUnavailable):
        await backend.add_document(None, "a.md", [], tenant_id="t")
