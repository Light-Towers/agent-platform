# -*- coding: utf-8 -*-
"""kb_delete 软删除逻辑单测（注入缝，零 Milvus/Mongo 依赖）。

钉五件事：
1. revoke_document 读→删→用 REVOKED 重插（向量原样、去主键）+ 登记回写；
2. 读不到切片 ⇒ found=False 不删不插（幂等/空库保护）；
3. 删除/插入的 filter 严格含 tenant + knowledge_id（租户隔离）；
4. has_active_documents：非 REVOKED 登记文档存在 ⇒ True；全 REVOKED ⇒ False；
5. delete_collection_guard：有有效文档拒绝；全部 REVOKED 才标 deleted。
"""
from __future__ import annotations

from knowledge_service.utils import kb_delete


class _FakeClient:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.deletes = []
        self.inserts = []

    def query(self, **kw):
        self.last_query = kw
        return [dict(r) for r in self.rows]

    def delete(self, **kw):
        self.deletes.append(kw)

    def insert(self, **kw):
        self.inserts.append(kw)


def _row(kid="kb1", status="PUBLISHED", tenant="t", source_doc="f.md"):
    return {
        "content": "text", "title": "h", "parent_title": "", "part": 0,
        "file_title": "f.md", "item_name": "", "tenant_id": tenant,
        "scope_type": "PRIVATE", "knowledge_id": kid, "workspace_id": "default",
        "status": status, "embedding_model": "bge-m3", "chunk_version": "v1",
        "created_at": 1, "source_doc": source_doc,
        "dense_vector": [0.1] * 1024, "sparse_vector": {1: 0.5},
        "chunk_id": 999,  # 主键，重插应去掉
    }


def test_revoke_document_read_delete_reinsert():
    client = _FakeClient(rows=[_row(), _row()])
    called = []
    res = kb_delete.revoke_document(
        client, "col", "t", "kb1",
        update_registry=lambda t, k, s: called.append((t, k, s)) or True,
    )
    assert res == {"deleted_chunks": 2, "revoked_chunks": 2, "registry_updated": True, "found": True, "source_doc": ""}
    assert len(client.deletes) == 1
    assert len(client.inserts) == 1
    inserted = client.inserts[0]["data"]
    assert len(inserted) == 2
    assert all(r["status"] == kb_delete.REVOKED for r in inserted)
    assert all("chunk_id" not in r for r in inserted)  # 去主键
    assert inserted[0]["dense_vector"] == [0.1] * 1024  # 向量原样
    assert called == [("t", "kb1", "REVOKED")]


def test_revoke_document_tenant_scoped_filter():
    client = _FakeClient(rows=[_row()])
    kb_delete.revoke_document(client, "col", "tenantA", "kb1")
    dfilter = client.deletes[0]["filter"]
    assert 'tenant_id == "tenantA"' in dfilter
    assert 'knowledge_id == "kb1"' in dfilter
    qfilter = client.last_query["filter"]
    assert 'tenant_id == "tenantA"' in qfilter


def test_revoke_document_empty_noop():
    client = _FakeClient(rows=[])
    res = kb_delete.revoke_document(client, "col", "t", "kb1")
    assert res["found"] is False
    assert client.deletes == [] and client.inserts == []


class _FilterAwareClient:
    """按 source_doc filter 返回对应文档切片，模拟多文档库。"""

    def __init__(self, rows):
        self.rows = rows
        self.deletes = []
        self.inserts = []

    def query(self, **kw):
        f = kw["filter"]
        if "source_doc !=" in f:  # has_other_active_docs
            target = f.split('source_doc != "')[1].split('"')[0]
            return [dict(r) for r in self.rows if r.get("source_doc") != target]
        if "source_doc ==" in f:  # read_chunks 单文档
            target = f.split('source_doc == "')[1].split('"')[0]
            return [dict(r) for r in self.rows if r.get("source_doc") == target]
        return [dict(r) for r in self.rows]

    def delete(self, **kw):
        self.deletes.append(kw)

    def insert(self, **kw):
        self.inserts.append(kw)


def test_revoke_single_doc_keeps_registry_when_others_active():
    """多文档库删其中一份：只下线该文档的切片，登记表不标 REVOKED。"""
    rows = [_row(source_doc="a.md"), _row(source_doc="b.md")]
    client = _FilterAwareClient(rows)
    called = []
    res = kb_delete.revoke_document(
        client, "col", "t", "kb1", source_doc="a.md",
        update_registry=lambda t, k, s: called.append((t, k, s)) or True,
    )
    assert res["found"] is True and res["source_doc"] == "a.md"
    assert 'source_doc == "a.md"' in client.deletes[0]["filter"]  # 删除只定位该文档
    assert called == []  # b.md 仍有效 → 不回写登记表


def test_revoke_single_doc_updates_registry_when_last():
    """删掉最后一份有效文档：登记表标 REVOKED。"""
    client = _FilterAwareClient([_row(source_doc="a.md")])
    called = []
    kb_delete.revoke_document(
        client, "col", "t", "kb1", source_doc="a.md",
        update_registry=lambda t, k, s: called.append((t, k, s)) or True,
    )
    assert called == [("t", "kb1", "REVOKED")]


def test_has_active_documents():
    active = [{"knowledge_id": "kb1", "status": "PUBLISHED"}]
    assert kb_delete.has_active_documents("t", "kb1", list_by_tenant=lambda *a, **k: active) is True
    revoked = [{"knowledge_id": "kb1", "status": "REVOKED"}]
    assert kb_delete.has_active_documents("t", "kb1", list_by_tenant=lambda *a, **k: revoked) is False
    other = [{"knowledge_id": "kb2", "status": "PUBLISHED"}]
    assert kb_delete.has_active_documents("t", "kb1", list_by_tenant=lambda *a, **k: other) is False


def test_delete_collection_guard():
    marked = []
    ok, msg = kb_delete.delete_collection_guard(
        "t", "kb1",
        list_by_tenant=lambda *a, **k: [{"knowledge_id": "kb1", "status": "PUBLISHED"}],
        mark_deleted=lambda t, k: marked.append((t, k)) or True,
    )
    assert ok is False and "有效文档" in msg
    assert marked == []

    ok, msg = kb_delete.delete_collection_guard(
        "t", "kb1",
        list_by_tenant=lambda *a, **k: [{"knowledge_id": "kb1", "status": "REVOKED"}],
        mark_deleted=lambda t, k: marked.append((t, k)) or True,
    )
    assert ok is True
    assert marked == [("t", "kb1")]
