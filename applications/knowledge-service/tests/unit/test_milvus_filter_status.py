# -*- coding: utf-8 -*-
"""Milvus 检索过滤的 v3 软删除判据单测（plan-kb-delete-and-management P2）。

钉三件事：
1. build_retrieval_filter 任何入参都带 status != REVOKED（老数据 status 空仍可召回）；
2. 与 tenant/knowledge/scope 子句用 and 正确组合；
3. 全空入参不再返回 None（v3 起至少含 status 过滤）。
"""
from __future__ import annotations

from knowledge_service.utils.milvus_filter_utils import (
    build_retrieval_filter,
    build_status_filter,
)


def test_status_filter_value():
    assert build_status_filter() == 'status != "REVOKED"'


def test_retrieval_filter_always_has_status_clause():
    # 全空入参：v3 起也应返回 status 过滤，不是 None
    only_status = build_retrieval_filter()
    assert only_status == 'status != "REVOKED"'

    # 带租户/知识库/scope：status 打头，and 组合
    full = build_retrieval_filter(
        item_names=["widget"], tenant_id="t1", scope_type="PUBLIC", knowledge_id="kb-1"
    )
    assert full.startswith('status != "REVOKED" and ')
    assert 'tenant_id == "t1"' in full
    assert 'scope_type == "PUBLIC"' in full
    assert 'knowledge_id == "kb-1"' in full
    assert 'item_name in ["widget"]' in full
