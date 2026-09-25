"""embed + rerank 契约测试：降级/错误分支/配置。"""

from __future__ import annotations

import pytest


class TestEmbedTexts:
    async def test_empty_list_returns_empty(self):
        from agent_server.rag.embed import embed_texts

        result = await embed_texts([])
        assert result == []


class TestEmbedQuery:
    async def test_single_text(self):
        from agent_server.rag.embed import embed_query

        result = await embed_query("test")
        assert isinstance(result, list)
        assert len(result) > 0


class TestApiReranker:
    def test_no_key_raises(self):
        from agent_server.rag.rerank import ApiReranker

        with pytest.raises(ValueError, match="未配置"):
            ApiReranker(api_key="")

    def test_init_with_key(self):
        from agent_server.rag.rerank import ApiReranker

        r = ApiReranker(api_key="test-key")
        assert r.api_key == "test-key"
        assert r.model == "BAAI/bge-reranker-v2-m3"

    def test_init_custom_model(self):
        from agent_server.rag.rerank import ApiReranker

        r = ApiReranker(api_key="key", model="custom-model")
        assert r.model == "custom-model"

    def test_compute_score_empty_input(self):
        from agent_server.rag.rerank import ApiReranker

        r = ApiReranker(api_key="key")
        assert r.compute_score([]) == []


class TestGetReranker:
    def test_disabled_returns_none(self, monkeypatch):
        from agent_server.rag.rerank import get_reranker

        monkeypatch.setenv("RERANK_ENABLED", "false")
        monkeypatch.setenv("RERANK_API_KEY", "")
        get_reranker.cache_clear()
        from agent_server.config import get_settings

        get_settings.cache_clear()
        result = get_reranker()
        assert result is None
        get_reranker.cache_clear()
        get_settings.cache_clear()
