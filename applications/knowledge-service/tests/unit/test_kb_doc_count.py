# -*- coding: utf-8 -*-
"""kb_doc_count 单测：/collections 的 doc_count 与 /documents/tree 同口径。"""
from __future__ import annotations

from knowledge_service.utils.kb_doc_count import count_docs_by_kb


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.last_query = None

    def query(self, **kw):
        self.last_query = kw
        return [dict(r) for r in self.rows]


def test_distinct_source_doc_per_kb():
    rows = [
        {"knowledge_id": "kb1", "source_doc": "a.pdf"},
        {"knowledge_id": "kb1", "source_doc": "a.pdf"},  # 同文档多切片 → 计 1
        {"knowledge_id": "kb1", "source_doc": "b.pdf"},
        {"knowledge_id": "kb2", "source_doc": "c.pdf"},
        {"knowledge_id": "", "source_doc": "orphan.pdf"},  # 空 kid 跳过
    ]
    out = count_docs_by_kb(_FakeClient(rows), "col", "t")
    assert out == {"kb1": 2, "kb2": 1}


def test_empty_source_doc_counted_as_one():
    rows = [{"knowledge_id": "kb1", "source_doc": ""}]
    assert count_docs_by_kb(_FakeClient(rows), "col", "t") == {"kb1": 1}


def test_empty_rows():
    assert count_docs_by_kb(_FakeClient([]), "col", "t") == {}


def test_query_is_tenant_scoped():
    client = _FakeClient([])
    count_docs_by_kb(client, "col", "tenantA")
    assert 'tenant_id == "tenantA"' in client.last_query["filter"]
