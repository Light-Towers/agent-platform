# -*- coding: utf-8 -*-
"""sparse_consistency self-retrieval canary 单测（纯逻辑，不连 Milvus / 不加载模型）。

覆盖：一致/不一致判定、集合空/空稀疏放行、dict 与 entity 两种命中形态、进程缓存与重置。
"""

import pytest

from knowledge_service.utils.sparse_consistency import (
    SparseEncodingMismatchError,
    assert_sparse_encoding_consistent,
    reset_sparse_consistency_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_sparse_consistency_cache()
    yield
    reset_sparse_consistency_cache()


class FakeClient:
    """仅实现 canary 用到的 query/search；记录调用次数供断言。"""

    def __init__(self, probe_rows, search_hits):
        self._probe_rows = probe_rows
        self._search_hits = search_hits
        self.query_calls = 0
        self.search_calls = 0

    def query(self, **kwargs):
        self.query_calls += 1
        return self._probe_rows

    def search(self, **kwargs):
        self.search_calls += 1
        return self._search_hits


def _embed(content):
    return {6: 0.5, 32: 0.5}


def test_consistent_flat_dict_hits_self():
    client = FakeClient(
        probe_rows=[{"chunk_id": 123, "content": "观众人数说明"}],
        search_hits=[[{"chunk_id": 123, "distance": 1.0}]],
    )
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed) is True
    assert client.search_calls == 1


def test_consistent_entity_nested_hits_self():
    client = FakeClient(
        probe_rows=[{"chunk_id": 456, "content": "烫金机参数"}],
        search_hits=[[{"entity": {"chunk_id": 456}, "distance": 0.98}]],
    )
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed) is True


def test_inconsistent_self_not_in_hits_raises():
    # 库内 md5 编码，查询用 BGE-M3 token id → 自检索命不中自身 → 抛错
    client = FakeClient(
        probe_rows=[{"chunk_id": 789, "content": "观众人数说明"}],
        search_hits=[[{"chunk_id": 111, "distance": 0.0}, {"chunk_id": 222, "distance": 0.0}]],
    )
    with pytest.raises(SparseEncodingMismatchError):
        assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed)


def test_empty_collection_skips_without_search():
    client = FakeClient(probe_rows=[], search_hits=[])
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed) is True
    assert client.search_calls == 0


def test_empty_content_skips_without_search():
    client = FakeClient(probe_rows=[{"chunk_id": 1, "content": ""}], search_hits=[])
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed) is True
    assert client.search_calls == 0


def test_empty_sparse_from_embed_skips_without_search():
    client = FakeClient(
        probe_rows=[{"chunk_id": 1, "content": "abc"}],
        search_hits=[[{"chunk_id": 1, "distance": 1.0}]],
    )
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=lambda _c: {}) is True
    assert client.search_calls == 0


def test_cache_short_circuits_second_call():
    client = FakeClient(
        probe_rows=[{"chunk_id": 123, "content": "x"}],
        search_hits=[[{"chunk_id": 123, "distance": 1.0}]],
    )
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed) is True
    # 第二次命中进程缓存，不再触发 query/search
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed) is True
    assert client.query_calls == 1
    assert client.search_calls == 1


def test_use_cache_false_rechecks():
    client = FakeClient(
        probe_rows=[{"chunk_id": 123, "content": "x"}],
        search_hits=[[{"chunk_id": 123, "distance": 1.0}]],
    )
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed, use_cache=False) is True
    assert assert_sparse_encoding_consistent(client, "coll", embed_sparse=_embed, use_cache=False) is True
    assert client.query_calls == 2
