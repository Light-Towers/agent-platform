# -*- coding: utf-8 -*-
"""ADR-0017/T5：BM25 腿传原文、旧 learned sparse 腿保留（纯离线单测，不连 Milvus）。"""

from knowledge_service.clients.milvus_utils import create_hybrid_search_requests


def test_bm25_engine_leg_uses_raw_text_and_bm25_metric():
    reqs = create_hybrid_search_requests(
        dense_vector=[0.1, 0.2],
        query_text="HAK-180 烫金机怎么用",
        expr="tenant_id == 't1'",
        limit=7,
        lexical_mode="bm25_engine",
    )
    dense_req, lexical_req = reqs
    assert dense_req.anns_field == "dense_vector"
    assert lexical_req.anns_field == "bm25_sparse"
    assert lexical_req.data == ["HAK-180 烫金机怎么用"]
    assert lexical_req.param == {"metric_type": "BM25"}
    assert lexical_req.limit == 7


def test_learned_sparse_legacy_leg_still_available():
    reqs = create_hybrid_search_requests(
        dense_vector=[0.1, 0.2],
        sparse_vector={1: 0.5},
        limit=3,
        lexical_mode="learned_sparse",
    )
    assert reqs[1].anns_field == "sparse_vector"
    assert reqs[1].param == {"metric_type": "IP"}


def test_bm25_engine_requires_raw_text():
    import pytest

    with pytest.raises(ValueError):
        create_hybrid_search_requests(dense_vector=[0.1], lexical_mode="bm25_engine")
