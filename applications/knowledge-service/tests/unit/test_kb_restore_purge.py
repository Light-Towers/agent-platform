# -*- coding: utf-8 -*-
"""restore_document / purge_document 纯函数单测（零 Milvus/Mongo）。"""
from __future__ import annotations

from knowledge_service.utils.kb_delete import purge_document, restore_document


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.deleted = []
        self.inserted = []

    def query(self, **kw):
        return [dict(r) for r in self.rows]

    def delete(self, **kw):
        self.deleted.append(kw)

    def insert(self, **kw):
        self.inserted.append(kw)


def _row(status):
    return {"status": status, "source_doc": "docA", "knowledge_id": "kb1", "content": "x"}


def test_restore_revoked_to_published():
    c = _Client([_row("REVOKED"), _row("REVOKED")])
    called = []
    r = restore_document(c, "col", "t", "kb1", source_doc="docA",
                         update_registry=lambda t, k, s: called.append(s) or True)
    assert r["found"] and r["restored_chunks"] == 2
    assert all(r["status"] == "PUBLISHED" for r in c.inserted[0]["data"])
    assert called == ["PUBLISHED"]


def test_restore_noop_when_not_revoked():
    c = _Client([_row("PUBLISHED")])
    r = restore_document(c, "col", "t", "kb1", source_doc="docA")
    assert r["found"] is False and c.inserted == []


def test_purge_deletes_without_reinsert():
    c = _Client([_row("REVOKED"), _row("REVOKED")])
    called = []
    r = purge_document(c, "col", "t", "kb1", source_doc="docA",
                       delete_registry=lambda t, k: called.append((t, k)) or True)
    assert r["found"] and r["deleted_chunks"] == 2
    assert c.inserted == []  # 真删除：不重插
    assert called == [("t", "kb1")]


def test_purge_empty():
    c = _Client([])
    r = purge_document(c, "col", "t", "kb1", source_doc="docA")
    assert r["found"] is False
