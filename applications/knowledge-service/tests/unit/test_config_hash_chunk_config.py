# -*- coding: utf-8 -*-
"""刀 4 F-15：config_hash 纳入切分参数 + run 快照读取（零 Milvus，纯函数/文件）。

钉三件事：
1. 不传 chunk_config 时哈希与旧行为一致（向后兼容，两个调用结果相同）；
2. 传入 chunk_config 时哈希改变，且不同切分参数得到不同哈希（可区分）；
3. _read_chunk_config_snapshot 从 registry 读出快照，缺失/占位值时回落 None。
"""
from __future__ import annotations

from knowledge_service.conf.config_hash import compute_config_hash


def test_hash_backward_compatible_when_no_chunk_config() -> None:
    assert compute_config_hash() == compute_config_hash(None)


def test_hash_changes_with_chunk_config() -> None:
    base = compute_config_hash()
    c1 = {"split_strategy": "title", "max_content_length": 2000, "chunk_overlap": 200}
    c2 = {"split_strategy": "char", "max_content_length": 1000, "chunk_overlap": 100}
    h1 = compute_config_hash(chunk_config=c1)
    h2 = compute_config_hash(chunk_config=c2)
    assert h1 != base            # 纳入切分参数后与旧哈希不同
    assert h1 != h2              # 不同切分参数可区分
    assert h1 == compute_config_hash(chunk_config=c1)  # 同参数可复现


def test_hash_chunk_config_key_order_stable() -> None:
    a = {"split_strategy": "title", "max_content_length": 2000, "chunk_overlap": 200}
    b = {"chunk_overlap": 200, "max_content_length": 2000, "split_strategy": "title"}
    assert compute_config_hash(chunk_config=a) == compute_config_hash(chunk_config=b)


def test_read_chunk_config_snapshot(monkeypatch) -> None:
    import eval.run_eval as reval

    fake_registry = {
        "col_x": {"chunk_params": {
            "split_strategy": "char", "max_content_length": 1500, "chunk_overlap": 150,
            "chunk_overlap_ratio": 0.1,
        }},
    }
    monkeypatch.setattr("knowledge_service.utils.index_registry.read_registry", lambda: fake_registry)
    snap = reval._read_chunk_config_snapshot("col_x")
    assert snap == {
        "split_strategy": "char", "max_content_length": 1500, "chunk_overlap": 150,
        "chunk_overlap_ratio": 0.1,
    }


def test_read_snapshot_returns_none_when_missing_or_placeholder(monkeypatch) -> None:
    import eval.run_eval as reval

    monkeypatch.setattr("knowledge_service.utils.index_registry.read_registry", lambda: {})
    assert reval._read_chunk_config_snapshot("col_x") is None
    # 旧占位值（max_len/merge_short）视为无有效快照
    monkeypatch.setattr(
        "knowledge_service.utils.index_registry.read_registry",
        lambda: {"col_x": {"chunk_params": {"max_len": None, "merge_short": True}}},
    )
    assert reval._read_chunk_config_snapshot("col_x") is None
