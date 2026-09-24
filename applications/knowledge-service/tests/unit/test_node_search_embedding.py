# -*- coding: utf-8 -*-
"""node_search_embedding 单测（knowledge-service）。

覆盖 F3 通用知识库修复：
- item_names 为空时不提前返回，继续执行检索（通用知识库场景）
- rewritten_query 缺失时 fallback 到 original_query
- item_names 有值时正常构造过滤表达式（既有商品手册场景不回归）
"""

from unittest.mock import patch

from knowledge_service.query_process.agent.nodes.node_search_embedding import node_search_embedding

_FAKE_EMBEDDING = {"dense": [[0.1, 0.2, 0.3]], "sparse": [{"key": 0, "value": 0.5}]}
_FAKE_HITS = [
    {"entity": {"chunk_id": "c1", "content": "展览搭建要求", "item_name": "搭建商手册"}, "distance": 0.95},
]


def _base_state(**overrides):
    state = {
        "session_id": "test-session",
        "original_query": "展览搭建商手册有哪些要求？",
        "rewritten_query": None,
        "item_names": [],
        "is_stream": False,
    }
    state.update(overrides)
    return state


@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.hybrid_search", return_value=[_FAKE_HITS])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.create_hybrid_search_requests", return_value=["fake_req"])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.get_milvus_client", return_value="fake_client")
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.generate_embeddings", return_value=_FAKE_EMBEDDING)
def test_empty_item_names_proceeds_with_search(_mock_emb, _mock_client, _mock_reqs, _mock_search):
    """item_names 为空时不提前返回，仍执行 Milvus 检索（通用知识库场景）。"""
    state = _base_state(item_names=[], rewritten_query="展览搭建要求")
    result = node_search_embedding(state)
    assert result["embedding_chunks"] == _FAKE_HITS
    assert _mock_search.call_count == 1


@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.hybrid_search", return_value=[_FAKE_HITS])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.create_hybrid_search_requests", return_value=["fake_req"])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.get_milvus_client", return_value="fake_client")
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.generate_embeddings", return_value=_FAKE_EMBEDDING)
def test_rewritten_query_fallback_to_original(_mock_emb, _mock_client, _mock_reqs, _mock_search):
    """rewritten_query 缺失时 fallback 到 original_query，不因 query=None 崩溃。"""
    state = _base_state(rewritten_query=None, original_query="展览展示工程服务基本要求")
    result = node_search_embedding(state)
    assert result["embedding_chunks"] == _FAKE_HITS
    call_args = _mock_emb.call_args
    assert call_args[0][0] == ["展览展示工程服务基本要求"]


@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.hybrid_search", return_value=[_FAKE_HITS])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.create_hybrid_search_requests", return_value=["fake_req"])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.get_milvus_client", return_value="fake_client")
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.generate_embeddings", return_value=_FAKE_EMBEDDING)
def test_item_names_present_still_works(_mock_emb, _mock_client, _mock_reqs, _mock_search):
    """item_names 有值时正常检索（既有商品手册场景不回归）。"""
    state = _base_state(item_names=["搭建商手册"], rewritten_query="搭建商手册有哪些要求")
    result = node_search_embedding(state)
    assert result["embedding_chunks"] == _FAKE_HITS
    assert _mock_search.call_count == 1


@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.hybrid_search", return_value=[[]])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.create_hybrid_search_requests", return_value=["fake_req"])
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.get_milvus_client", return_value="fake_client")
@patch("knowledge_service.query_process.agent.nodes.node_search_embedding.generate_embeddings", return_value=_FAKE_EMBEDDING)
def test_empty_item_names_no_results_returns_empty(_mock_emb, _mock_client, _mock_reqs, _mock_search):
    """item_names 为空且 Milvus 无结果时返回空列表（非提前返回，而是检索后无结果）。"""
    state = _base_state(item_names=[], rewritten_query="不存在的查询")
    result = node_search_embedding(state)
    assert result["embedding_chunks"] == []
    assert _mock_search.call_count == 1
