# -*- coding: utf-8 -*-
"""
test_rerank_api_mode.py —— 验证 reranker_utils 的 api 模式（M8）。

【不依赖重型依赖 / 不依赖 FlagEmbedding / pymilvus.model，可在裸 venv 运行。】
验证方式：mock app.lm.siliconflow_client._post_json（不真调网络）。
验证重点：
1. RERANK_MODE=api 时 get_reranker_model() 返回 ApiReranker（与 FlagReranker.compute_score 同签名）；
2. compute_score 分数解析正确、返回顺序与输入 sentence_pairs 一致（即使 API 乱序返回）；
3. 多 query 分组调用语义正确；
4. 空入参返回空列表。
"""

import pytest

from app.conf.reranker_config import reranker_config
from app.lm import reranker_utils
from app.lm.reranker_utils import get_reranker_model


def _enable_api_mode(monkeypatch):
    """将 rerank 配置切到 api 模式并重置单例。"""
    monkeypatch.setattr(reranker_config, "rerank_mode", "api")
    monkeypatch.setattr(reranker_config, "siliconflow_api_key", "test-key")
    monkeypatch.setattr(reranker_config, "siliconflow_base_url", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(reranker_config, "siliconflow_rerank_model", "BAAI/bge-reranker-v2-m3")
    monkeypatch.setattr(reranker_utils, "_api_reranker", None)


def test_default_mode_is_local():
    # 默认（不改配置）必须是 local，保证向后兼容铁律
    assert reranker_config.rerank_mode == "local"


def test_get_reranker_model_returns_api_reranker(monkeypatch):
    _enable_api_mode(monkeypatch)
    reranker = get_reranker_model()
    # api 模式返回 ApiReranker，具备与 FlagReranker 同名的 compute_score
    assert reranker.__class__.__name__ == "ApiReranker"
    assert callable(getattr(reranker, "compute_score"))


def test_compute_score_order_and_values(monkeypatch):
    _enable_api_mode(monkeypatch)

    def fake_post_json(url, headers, payload, **kwargs):
        assert url.endswith("/rerank")
        assert headers["Authorization"] == "Bearer test-key"
        assert payload["model"] == "BAAI/bge-reranker-v2-m3"
        docs = payload["documents"]
        # 模拟 API 乱序返回（带 index）：1/(i+1) 分数
        results = [{"index": i, "relevance_score": 1.0 / (i + 1)} for i in range(len(docs))]
        results.reverse()
        return {"id": "rerank-1", "results": results}

    monkeypatch.setattr("app.lm.siliconflow_client._post_json", fake_post_json)

    reranker = get_reranker_model()
    pairs = [["什么是RRF？", "RRF是倒数排名融合算法"], ["什么是RRF？", "FP16是半精度推理"], ["什么是RRF？", "无关内容"]]
    scores = reranker.compute_score(pairs)

    # 返回顺序与输入一致：doc1->1.0, doc2->0.5, doc3->1/3（分数越高越相关）
    assert len(scores) == 3
    assert abs(scores[0] - 1.0) < 1e-9
    assert abs(scores[1] - 0.5) < 1e-9
    assert abs(scores[2] - 1.0 / 3.0) < 1e-9
    assert scores[0] > scores[1] > scores[2]


def test_compute_score_multiple_queries_grouping(monkeypatch):
    _enable_api_mode(monkeypatch)

    calls = []

    def fake_post_json(url, headers, payload, **kwargs):
        calls.append(payload)
        docs = payload["documents"]
        # 同一 query 的 docs 分数：按顺序 0.9, 0.8, ...（此处每个 query 的 docs 数 ≤2）
        results = [{"index": i, "relevance_score": 0.9 - 0.1 * i} for i in range(len(docs))]
        return {"id": "rerank-x", "results": results}

    monkeypatch.setattr("app.lm.siliconflow_client._post_json", fake_post_json)

    reranker = get_reranker_model()
    pairs = [["q1", "d1"], ["q2", "d2"], ["q1", "d3"]]
    scores = reranker.compute_score(pairs)

    # 两个 query 各一次调用（按首次出现顺序：q1 先、q2 后）
    assert len(calls) == 2
    assert calls[0]["query"] == "q1" and calls[0]["documents"] == ["d1", "d3"]
    assert calls[1]["query"] == "q2" and calls[1]["documents"] == ["d2"]

    # 返回顺序与输入 pairs 一一对应：q1-d1->0.9, q2-d2->0.9, q1-d3->0.8
    assert len(scores) == 3
    assert abs(scores[0] - 0.9) < 1e-9
    assert abs(scores[1] - 0.9) < 1e-9
    assert abs(scores[2] - 0.8) < 1e-9


def test_compute_score_empty_pairs_returns_empty(monkeypatch):
    _enable_api_mode(monkeypatch)
    reranker = get_reranker_model()
    assert reranker.compute_score([]) == []


def test_compute_score_invalid_pair_raises(monkeypatch):
    _enable_api_mode(monkeypatch)
    reranker = get_reranker_model()
    with pytest.raises(ValueError, match="二元组"):
        reranker.compute_score([["只有query没有doc"]])


def test_api_mode_requires_api_key(monkeypatch):
    monkeypatch.setattr(reranker_config, "rerank_mode", "api")
    monkeypatch.setattr(reranker_config, "siliconflow_api_key", "")
    monkeypatch.setattr(reranker_utils, "_api_reranker", None)

    with pytest.raises(RuntimeError, match="SILICONFLOW_API_KEY"):
        get_reranker_model()


def test_api_mode_missing_score_field_raises(monkeypatch):
    _enable_api_mode(monkeypatch)

    def fake_post_json(url, headers, payload, **kwargs):
        return {"id": "x", "results": [{"index": 0}]}  # 缺 relevance_score

    monkeypatch.setattr("app.lm.siliconflow_client._post_json", fake_post_json)

    reranker = get_reranker_model()
    with pytest.raises(RuntimeError, match="relevance_score"):
        reranker.compute_score([["q", "d"]])
