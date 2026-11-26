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


def test_milvus_analyzer_params_matches_poc_version() -> None:
    # T2 真机实测：v2.5.10 只接受简单 jieba 配置，自定义 dict/mode/hmm 会建集合失败。
    assert milvus_analyzer_params() == {"tokenizer": "jieba"}
