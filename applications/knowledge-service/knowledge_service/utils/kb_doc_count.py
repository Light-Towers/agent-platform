# -*- coding: utf-8 -*-
"""知识库真实文档数聚合（供 GET /collections 的 doc_count 字段）。

背景：kb_collections 的冗余 doc_count 恒 0（无人维护），而前端对话页「知识范围」下拉
与知识库页左栏都读 GET /kb/knowledge-bases → KS /collections。若该端点返回恒 0，
两页就都显示「0 篇」，且与知识库页左栏（从 /documents/tree 取真实数）不一致。
⇒ /collections 实时按 Milvus 的 (knowledge_id, source_doc) 聚合出每个库的 distinct
文档数，两页读同一端点同一字段即天然一致；viewer（chat.run）也能拿到，
不必给 viewer 开 /documents/tree（那会暴露全部切片正文）。

文档数口径 = 该库 distinct source_doc 数（与 /documents/tree 的 doc_count 完全一致）。
不按 status 过滤：REVOKED 文档仍"存在"，下线语义由检索侧 status 谓词负责。

模块无 KS 硬依赖（client 注入缝），零 Milvus 可单测。
"""
from __future__ import annotations

from typing import Any, Dict


def count_docs_by_kb(
    client: Any, collection: str, tenant_id: str, *, limit: int = 16384,
) -> Dict[str, int]:
    """从 Milvus 聚合每个 knowledge_id 的 distinct source_doc 数。

    :param client: MilvusClient（注入缝，零依赖单测）；None 时调用方应降级为全 0。
    :returns: {knowledge_id: doc_count}，只含 knowledge_id 非空的切片。
    """
    rows = client.query(
        collection_name=collection,
        filter=f'tenant_id == "{tenant_id}"',
        output_fields=["knowledge_id", "source_doc"],
        limit=limit,
    ) or []
    docs_by_kb: dict[str, set[str]] = {}
    for r in rows:
        kid = str(r.get("knowledge_id") or "").strip()
        if not kid:
            continue
        source_doc = str(r.get("source_doc") or "").strip() or "未命名文档"
        docs_by_kb.setdefault(kid, set()).add(source_doc)
    return {kid: len(docs) for kid, docs in docs_by_kb.items()}


__all__ = ["count_docs_by_kb"]
