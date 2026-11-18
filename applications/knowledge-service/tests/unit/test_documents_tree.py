# -*- coding: utf-8 -*-
"""documents_tree 聚合逻辑单测（纯函数口径：按 knowledge_id + source_doc 聚合 chunk）。

钉三件事：
1. 同库同文档多切片 → 聚合成 1 文档 + N 切片；
2. 同库不同文档 → 多个文档，doc_count = 文档数（非切片数）；
3. 空 knowledge_id 的 chunk 不进树；租户过滤在 query 层（此处只验聚合形状）。
"""
from __future__ import annotations

from collections import defaultdict


# 与 import_router.documents_tree 内聚合逻辑同形（抽出来便于零依赖单测）
def aggregate_tree(rows: list[dict]) -> list[dict]:
    tree: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        kid = str(r.get("knowledge_id") or "").strip()
        if not kid:
            continue
        source_doc = str(r.get("source_doc") or "").strip() or "未命名文档"
        tree[kid][source_doc].append({
            "part": r.get("part"),
            "title": str(r.get("title") or ""),
            "parent_title": str(r.get("parent_title") or ""),
            "content": str(r.get("content") or ""),
            "status": str(r.get("status") or ""),
        })
    result = []
    for kid, docs in tree.items():
        doc_list = []
        for source_doc, chunks in docs.items():
            chunks.sort(key=lambda c: (c["part"] if isinstance(c["part"], int) else 0))
            doc_list.append({"source_doc": source_doc, "chunk_count": len(chunks), "chunks": chunks})
        result.append({"knowledge_id": kid, "doc_count": len(doc_list), "documents": doc_list})
    result.sort(key=lambda x: x["knowledge_id"])
    return result


def test_aggregate_multi_chunks_one_doc():
    rows = [
        {"knowledge_id": "kb1", "source_doc": "a.pdf", "part": 1, "title": "h1", "content": "c1", "status": "PUBLISHED"},
        {"knowledge_id": "kb1", "source_doc": "a.pdf", "part": 0, "title": "h0", "content": "c0", "status": "PUBLISHED"},
    ]
    out = aggregate_tree(rows)
    assert len(out) == 1
    kb = out[0]
    assert kb["knowledge_id"] == "kb1"
    assert kb["doc_count"] == 1           # 1 个文档，不是 2 个切片
    assert kb["documents"][0]["chunk_count"] == 2
    assert [c["part"] for c in kb["documents"][0]["chunks"]] == [0, 1]  # 按 part 排序


def test_aggregate_multi_docs():
    rows = [
        {"knowledge_id": "kb1", "source_doc": "a.pdf", "part": 0, "content": "x", "status": "PUBLISHED"},
        {"knowledge_id": "kb1", "source_doc": "b.pdf", "part": 0, "content": "y", "status": "PUBLISHED"},
        {"knowledge_id": "kb2", "source_doc": "c.pdf", "part": 0, "content": "z", "status": "PUBLISHED"},
    ]
    out = aggregate_tree(rows)
    assert [k["knowledge_id"] for k in out] == ["kb1", "kb2"]
    assert out[0]["doc_count"] == 2   # kb1 有 a.pdf + b.pdf 两个文档
    assert sorted(d["source_doc"] for d in out[0]["documents"]) == ["a.pdf", "b.pdf"]


def test_aggregate_skips_empty_kid():
    rows = [
        {"knowledge_id": "", "source_doc": "orphan.pdf", "part": 0, "content": "x", "status": "PUBLISHED"},
        {"knowledge_id": "kb1", "source_doc": "a.pdf", "part": 0, "content": "y", "status": "PUBLISHED"},
    ]
    out = aggregate_tree(rows)
    assert len(out) == 1 and out[0]["knowledge_id"] == "kb1"
