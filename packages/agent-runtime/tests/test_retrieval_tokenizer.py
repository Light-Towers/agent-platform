"""T14 共享分词模块单测：混排切分、领域词完整、单一事实源、analyzer 同源派生。"""

from __future__ import annotations

import pytest

pytest.importorskip("jieba", reason="agent-runtime[tokenizer] extra 未安装")

from agent_runtime.retrieval_tokenizer import (  # noqa: E402
    DOMAIN_TERMS,
    get_tokenizer,
    milvus_analyzer_params,
)


def test_mixed_zh_en_tokens_are_independent() -> None:
    tokens = get_tokenizer().tokenize("HAK-180 烫金机怎么用")
    assert "hak-180" in tokens
    assert "烫金机" in tokens
    assert "怎么用" in tokens or "怎么" in tokens


def test_english_terms_are_lowercased_and_kept_whole() -> None:
    tokens = get_tokenizer().tokenize("BGE-M3 sparse 原理")
    assert "bge-m3" in tokens
    assert "sparse" in tokens
    assert "原理" in tokens


def test_domain_terms_are_registered_from_single_source() -> None:
    assert "烫金机" in DOMAIN_TERMS
    assert "向量数据库" in get_tokenizer().tokenize("向量数据库召回")


def test_empty_input_returns_empty_list() -> None:
    assert get_tokenizer().tokenize(None) == []
    assert get_tokenizer().tokenize("") == []


def test_milvus_analyzer_params_default_is_safe_for_online_2_5() -> None:
    # 线上仍是 v2.5.10，默认必须保持简单形式，否则建集合失败。
    assert milvus_analyzer_params() == {"tokenizer": "jieba"}


def test_milvus_analyzer_params_domain_dict_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    # 治本形态（Milvus 2.6 POC/升级后）：引擎侧 jieba 挂载领域词典文件。
    monkeypatch.setenv("RETRIEVAL_ANALYZER_PROFILE", "domain_dict_2_6")
    tok = milvus_analyzer_params()["tokenizer"]
    assert tok["type"] == "jieba"
    assert tok["dict"] == ["_default_"]
    assert tok["mode"] == "exact" and tok["hmm"] is True  # exact 保住领域词整词（POC 实测 search 会拆）
    assert tok["extra_dict_file"]["type"] == "local"
    assert tok["extra_dict_file"]["path"].endswith("zh_terms.txt")
