# -*- coding: utf-8 -*-
"""
test_embedding_api_mode.py —— 验证 embedding_utils 的 api 模式（M8）。

【不依赖重型依赖 / 不依赖 FlagEmbedding / pymilvus.model，可在裸 venv 运行。】
验证方式：mock app.lm.siliconflow_client._post_json（不真调网络）。
验证重点：
1. EMBEDDING_MODE=api 时 generate_embeddings 返回结构与 local 完全一致
   （{"dense": [...], "sparse": [...]}）；
2. api 稠密向量已本地 L2 归一化；
3. api 稀疏向量为 {int token_id: float 权重} 字典（本地生成，B 路线）；
4. local 模式不受影响（分发到本地实现）。
"""

import math

import pytest

from agent_core.memory import embedder as core_embedder
from app.conf.embedding_config import embedding_config
from app.lm import embedding_utils
from app.lm.embedding_utils import generate_embeddings


def _enable_api_mode(monkeypatch):
    """将 embedding 配置切到 api 模式并重置单例。"""
    monkeypatch.setattr(embedding_config, "embedding_mode", "api")
    monkeypatch.setattr(embedding_config, "siliconflow_api_key", "test-key")
    monkeypatch.setattr(embedding_config, "siliconflow_base_url", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(embedding_config, "siliconflow_embedding_model", "BAAI/bge-m3")
    monkeypatch.setattr(embedding_utils, "_api_embedding_client", None)


def test_default_mode_is_local():
    # 默认（不改配置）必须是 local，保证向后兼容铁律
    assert embedding_config.embedding_mode == "local"


def test_api_generate_embeddings_structure(monkeypatch):
    _enable_api_mode(monkeypatch)

    calls = []

    def fake_post_json(url, headers, payload, **kwargs):
        calls.append((url, headers, payload))
        n = len(payload["input"])
        # 模拟硅基流动响应：embedding=[3,4]（未归一化），index 乱序返回
        data = [{"object": "embedding", "index": i, "embedding": [3.0, 4.0]} for i in range(n)]
        data.reverse()
        return {"object": "list", "data": data}

    monkeypatch.setattr(core_embedder, "_http_post_json", fake_post_json)

    texts = ["苹果手机", "商品：苹果，介绍：支持5G网络"]
    res = generate_embeddings(texts)

    # 返回结构与 local 完全一致
    assert set(res.keys()) == {"dense", "sparse"}
    assert len(res["dense"]) == 2
    assert len(res["sparse"]) == 2

    # 稠密向量已 L2 归一化：[3,4] -> [0.6, 0.8]
    for vec in res["dense"]:
        assert abs(vec[0] - 0.6) < 1e-9
        assert abs(vec[1] - 0.8) < 1e-9
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-9

    # 稀疏向量为 {int: float} 字典（本地生成）
    for sv in res["sparse"]:
        assert isinstance(sv, dict)
        for k, w in sv.items():
            assert isinstance(k, int)
            assert isinstance(w, float)

    # 请求：地址为 /embeddings，头带 Bearer
    assert len(calls) == 1
    url, headers, payload = calls[0]
    assert url.endswith("/embeddings")
    assert headers["Authorization"] == "Bearer test-key"
    assert payload["model"] == "BAAI/bge-m3"
    assert payload["input"] == texts


def test_api_dense_order_matches_input(monkeypatch):
    # 即使 API 乱序返回（带 index），客户端按 index 重排，返回顺序与输入一致
    _enable_api_mode(monkeypatch)

    def fake_post_json(url, headers, payload, **kwargs):
        n = len(payload["input"])
        # 第 i 条向量 [i+1, 1]（归一化后首分量随 i 递增，可区分顺序）
        data = [{"object": "embedding", "index": i, "embedding": [float(i + 1), 1.0]} for i in range(n)]
        data.reverse()  # 乱序返回
        return {"object": "list", "data": data}

    monkeypatch.setattr(core_embedder, "_http_post_json", fake_post_json)

    res = generate_embeddings(["第一段", "第二段", "第三段"])
    # 每条向量 L2 归一化
    for vec in res["dense"]:
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-9
    # 首分量随输入顺序递增：index=0 的 [1,1]/√2 应排最前（0.7071 < 0.8944 < 0.9487）
    first_components = [vec[0] for vec in res["dense"]]
    assert first_components[0] < first_components[1] < first_components[2]
    assert abs(first_components[0] - 1.0 / math.sqrt(2.0)) < 1e-9
    assert abs(first_components[1] - 2.0 / math.sqrt(5.0)) < 1e-9
    assert abs(first_components[2] - 3.0 / math.sqrt(10.0)) < 1e-9


def test_api_mode_requires_api_key(monkeypatch):
    monkeypatch.setattr(embedding_config, "embedding_mode", "api")
    monkeypatch.setattr(embedding_config, "siliconflow_api_key", "")
    monkeypatch.setattr(embedding_utils, "_api_embedding_client", None)

    with pytest.raises(RuntimeError, match="SILICONFLOW_API_KEY"):
        generate_embeddings(["测试"])


def test_api_mode_missing_response_field_raises(monkeypatch):
    _enable_api_mode(monkeypatch)

    def fake_post_json(url, headers, payload, **kwargs):
        return {"object": "list", "data": [{"object": "embedding", "index": 0}]}  # 缺 embedding 字段

    monkeypatch.setattr(core_embedder, "_http_post_json", fake_post_json)

    with pytest.raises(RuntimeError, match="embedding"):
        generate_embeddings(["测试"])


def test_api_mode_wrong_count_raises(monkeypatch):
    _enable_api_mode(monkeypatch)

    def fake_post_json(url, headers, payload, **kwargs):
        # 返回条数少于请求
        return {"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0]}]}

    monkeypatch.setattr(core_embedder, "_http_post_json", fake_post_json)

    with pytest.raises(RuntimeError, match="数量不匹配"):
        generate_embeddings(["测试1", "测试2"])


def test_local_mode_dispatches_to_local_implementation(monkeypatch):
    # local 模式必须分发到本地实现（不触网、不初始化 api 客户端）
    monkeypatch.setattr(embedding_config, "embedding_mode", "local")
    called = {}

    def fake_local(texts):
        called["texts"] = texts
        return {"dense": [[1.0, 0.0]], "sparse": [{1: 1.0}]}

    monkeypatch.setattr(embedding_utils, "_generate_embeddings_local", fake_local)

    res = generate_embeddings(["本地文本"])
    assert res == {"dense": [[1.0, 0.0]], "sparse": [{1: 1.0}]}
    assert called["texts"] == ["本地文本"]


def test_unknown_mode_falls_back_to_local(monkeypatch):
    # 未知模式值回退 local（向后兼容铁律）
    monkeypatch.setattr(embedding_config, "embedding_mode", "unknown-mode")
    called = {}

    def fake_local(texts):
        called["texts"] = texts
        return {"dense": [[0.5, 0.5]], "sparse": [{}]}

    monkeypatch.setattr(embedding_utils, "_generate_embeddings_local", fake_local)

    res = generate_embeddings(["未知模式"])
    assert res["dense"] == [[0.5, 0.5]]
    assert called["texts"] == ["未知模式"]


def test_generate_embeddings_rejects_bad_input(monkeypatch):
    _enable_api_mode(monkeypatch)
    with pytest.raises(ValueError, match="texts"):
        generate_embeddings([])
    with pytest.raises(ValueError, match="texts"):
        generate_embeddings("不是列表")
