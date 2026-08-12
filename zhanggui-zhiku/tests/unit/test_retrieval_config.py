# -*- coding: utf-8 -*-
"""
test_retrieval_config.py —— M3 配置外置单测（方案 §7）。

验证：
1. `app/conf/retrieval.yaml` / `app/conf/rerank.yaml` 可加载，默认值与改造前硬编码一致
   （rrf.k=60、hybrid 0.8/0.2、dynamic_topk gap_ratio=0.25/gap_abs=0.5、max_k=10 等）；
2. 轻量加载器（yaml_config_utils.load_yaml_config）返回属性访问对象；
3. 配置值可被覆盖（环境变量指向替代 yaml 路径，部署 / 实验用）。

【不依赖重型依赖】：本文件只 import app.conf.retrieval_config / rerank_config /
yaml_config_utils（仅依赖 os / pathlib / yaml / pytest），可在纯 pytest 环境运行。
"""

import importlib
from pathlib import Path

import pytest

from app.conf import rerank_config, retrieval_config
from app.conf.yaml_config_utils import CfgDict, load_yaml_config


# ---------------------------------------------------------------------------
# 默认值 = 改造前硬编码（保证默认行为不变）
# ---------------------------------------------------------------------------
def test_retrieval_yaml_loads_with_expected_defaults():
    cfg = retrieval_config.retrieval_cfg
    # hybrid：原 node_search_embedding.py 硬编码 (0.8, 0.2)
    assert cfg.hybrid.dense_weight == pytest.approx(0.8)
    assert cfg.hybrid.sparse_weight == pytest.approx(0.2)
    # rrf：原 node_rrf.py:172 硬编码 k=60 / max_results=10 / weights (1.0, 1.0)
    assert cfg.rrf.k == 60
    assert cfg.rrf.max_results == 10
    assert cfg.rrf.weights["embedding"] == pytest.approx(1.0)
    assert cfg.rrf.weights["hyde"] == pytest.approx(1.0)
    # channels：逐路开关与超时（配合 §10.3，M6 fanout 使用）
    assert cfg.channels.embedding.enabled is True
    assert cfg.channels.embedding.timeout_s == pytest.approx(1.5)
    assert cfg.channels.hyde.timeout_s == pytest.approx(2.5)
    assert cfg.channels.kg.timeout_s == pytest.approx(1.0)
    assert cfg.channels.web.timeout_s == pytest.approx(3.0)


def test_rerank_yaml_loads_with_expected_defaults():
    cfg = rerank_config.rerank_cfg
    assert cfg.model == "BAAI/bge-reranker-v2-m3"
    assert cfg.batch_size == 16
    assert cfg.max_concurrency == 8
    # dynamic_topk：原 node_rerank.py 硬编码 gap_ratio=0.25 / gap_abs=0.5 / min=1 / max=10
    assert cfg.dynamic_topk.enabled is True
    assert cfg.dynamic_topk.gap_ratio == pytest.approx(0.25)
    assert cfg.dynamic_topk.gap_abs == pytest.approx(0.5)
    assert cfg.dynamic_topk.min_k == 1
    assert cfg.dynamic_topk.max_k == 10
    # fallback：异常返回原序（既有降级行为显式化）
    assert cfg.fallback.on_error == "passthrough"


# ---------------------------------------------------------------------------
# 轻量加载器
# ---------------------------------------------------------------------------
def test_loader_returns_attr_dict():
    cfg = load_yaml_config(Path("app/conf/retrieval.yaml"), "ZHANGUI_RETRIEVAL_YAML")
    assert isinstance(cfg, CfgDict)
    # 属性访问 + dict 访问 + 混合访问
    assert cfg.rrf.k == 60
    assert cfg.rrf.weights["embedding"] == pytest.approx(1.0)
    assert cfg.channels["embedding"]["timeout_s"] == pytest.approx(1.5)


def test_loader_env_override_path(tmp_path, monkeypatch):
    # 环境变量可指向替代 yaml（部署 / 实验覆盖路径）
    alt = tmp_path / "retrieval_alt.yaml"
    alt.write_text(
        "hybrid:\n"
        "  dense_weight: 0.6\n"
        "  sparse_weight: 0.4\n"
        "rrf:\n"
        "  k: 30\n"
        "  max_results: 5\n"
        "  weights:\n"
        "    embedding: 1.0\n"
        "    hyde: 0.6\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ZHANGUI_RETRIEVAL_YAML", str(alt))
    cfg = load_yaml_config(Path("app/conf/retrieval.yaml"), "ZHANGUI_RETRIEVAL_YAML")
    assert cfg.hybrid.dense_weight == pytest.approx(0.6)
    assert cfg.hybrid.sparse_weight == pytest.approx(0.4)
    assert cfg.rrf.k == 30
    assert cfg.rrf.weights["hyde"] == pytest.approx(0.6)


def test_loader_missing_yaml_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHANGUI_RERANK_YAML", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        load_yaml_config(Path("app/conf/rerank.yaml"), "ZHANGUI_RERANK_YAML")


# ---------------------------------------------------------------------------
# 模块级单例与环境变量覆盖
# ---------------------------------------------------------------------------
def test_module_singleton_respects_env_override(tmp_path, monkeypatch):
    alt = tmp_path / "retrieval_alt.yaml"
    alt.write_text(
        "hybrid:\n"
        "  dense_weight: 0.9\n"
        "  sparse_weight: 0.1\n"
        "rrf:\n"
        "  k: 100\n"
        "  max_results: 20\n"
        "  weights:\n"
        "    embedding: 1.0\n"
        "    hyde: 1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ZHANGUI_RETRIEVAL_YAML", str(alt))
    mod = importlib.reload(retrieval_config)
    try:
        assert mod.retrieval_cfg.hybrid.dense_weight == pytest.approx(0.9)
        assert mod.retrieval_cfg.rrf.k == 100
    finally:
        monkeypatch.delenv("ZHANGUI_RETRIEVAL_YAML", raising=False)
        importlib.reload(retrieval_config)  # 恢复默认配置，避免影响后续用例
    assert retrieval_config.retrieval_cfg.rrf.k == 60
