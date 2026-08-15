# -*- coding: utf-8 -*-
"""
test_ablation.py —— Dynamic TopK 消融策略纯函数单测（M3.5，方案 §6.4）。

覆盖 eval/ablation.py：
- 策略名解析（fixed_k=N / dynamic，含非法输入）；
- 固定截断行为（fixed_k=3/5/10 与 dynamic 在 mock 检索结果上的截断差异）；
- token 启发式估算函数；
- 文本字段提取（text / content 兼容）；
- 均值 / P95 统计与按策略聚合。

【不依赖重型依赖】：本文件只 import eval.ablation（纯 stdlib），不连 Milvus，
不 import run_ablation / run_eval（避免拉起重型依赖），与 tests/unit 其余用例一致。
"""

import pytest

from eval.ablation import (
    STRATEGIES,
    aggregate_strategy_rows,
    apply_strategy,
    compute_mean,
    compute_p95,
    estimate_tokens,
    extract_doc_text,
    parse_strategy,
    truncate_to_fixed_k,
)


# ---------------------------------------------------------------------------
# 策略名解析
# ---------------------------------------------------------------------------
def test_parse_strategy_fixed_k():
    assert parse_strategy("fixed_k=3") == ("fixed", 3)
    assert parse_strategy("fixed_k=10") == ("fixed", 10)


def test_parse_strategy_dynamic():
    assert parse_strategy("dynamic") == ("dynamic", None)


def test_parse_strategy_case_insensitive():
    assert parse_strategy("FIXED_K=5") == ("fixed", 5)
    assert parse_strategy("Dynamic") == ("dynamic", None)


def test_parse_strategy_invalid_raises():
    for bad in ("fixed_k=0", "fixed_k=-1", "fixed_k=abc", "unknown", ""):
        with pytest.raises(ValueError):
            parse_strategy(bad)


# ---------------------------------------------------------------------------
# 固定截断
# ---------------------------------------------------------------------------
def _mock_docs(n: int):
    return [{"chunk_id": str(i), "text": f"doc-{i}"} for i in range(1, n + 1)]


def test_truncate_to_fixed_k_basic():
    docs = _mock_docs(5)
    assert [d["chunk_id"] for d in truncate_to_fixed_k(docs, 3)] == ["1", "2", "3"]


def test_truncate_to_fixed_k_k_larger_than_len():
    docs = _mock_docs(5)
    assert len(truncate_to_fixed_k(docs, 10)) == 5


def test_truncate_to_fixed_k_zero_or_empty():
    assert truncate_to_fixed_k(_mock_docs(5), 0) == []
    assert truncate_to_fixed_k([], 3) == []


def test_apply_strategy_fixed_truncates():
    docs = _mock_docs(5)
    assert len(apply_strategy("fixed_k=3", docs)) == 3
    assert len(apply_strategy("fixed_k=5", docs)) == 5
    assert len(apply_strategy("fixed_k=10", docs)) == 5  # 候选不足 10 条 → 全保留


def test_apply_strategy_dynamic_passthrough():
    # dynamic 的截断逻辑在 node_rerank 内部执行，脚本层原样返回
    docs = _mock_docs(5)
    assert apply_strategy("dynamic", docs) == list(docs)


def test_apply_strategy_invalid_raises():
    with pytest.raises(ValueError):
        apply_strategy("fixed_k=abc", _mock_docs(3))


# ---------------------------------------------------------------------------
# token 估算（启发式）
# ---------------------------------------------------------------------------
def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_cjk_one_per_char():
    assert estimate_tokens("烫金机") == 3


def test_estimate_tokens_ascii_four_per_char():
    assert estimate_tokens("abcd") == 1  # int(4/4)=1
    assert estimate_tokens("a" * 20) == 5  # int(20/4)=5


def test_estimate_tokens_mixed():
    # 3 个 CJK + 4 个 ascii → int(3 + 4/4) = 4
    assert estimate_tokens("烫金机abcd") == 4


# ---------------------------------------------------------------------------
# 文本字段提取（rerank text / RRF content 兼容）
# ---------------------------------------------------------------------------
def test_extract_doc_text_prefers_text():
    assert extract_doc_text({"text": "abc", "content": "xyz"}) == "abc"


def test_extract_doc_text_falls_back_to_content():
    assert extract_doc_text({"text": "", "content": "xyz"}) == "xyz"


def test_extract_doc_text_missing():
    assert extract_doc_text({}) == ""
    assert extract_doc_text("not-a-dict") == ""


# ---------------------------------------------------------------------------
# 均值 / P95 / 聚合
# ---------------------------------------------------------------------------
def test_compute_mean():
    assert compute_mean([1, 2, 3, 4]) == pytest.approx(2.5)
    assert compute_mean([]) == 0.0


def test_compute_p95_known_values():
    assert compute_p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == pytest.approx(10.0)
    assert compute_p95([1]) == pytest.approx(1.0)
    assert compute_p95([1, 2, 3]) == pytest.approx(3.0)  # idx = ceil(2.85)-1 = 2
    assert compute_p95([]) == 0.0


def test_aggregate_strategy_rows_covers_all_strategies():
    per_query = {
        s: [
            {
                "metrics": {"recall@10": 0.5, "ndcg@10": 0.4},
                "returned": 3,
                "tokens_estimate": 100.0,
                "latency_ms": 10.0,
            }
        ]
        for s in STRATEGIES
    }
    rows = aggregate_strategy_rows(per_query)
    assert [r["strategy"] for r in rows] == list(STRATEGIES)
    for row in rows:
        assert row["recall@10"] == pytest.approx(0.5)
        assert row["ndcg@10"] == pytest.approx(0.4)
        assert row["avg_returned"] == pytest.approx(3.0)
        assert row["avg_tokens"] == pytest.approx(100.0)
        assert row["p95_latency_ms"] == pytest.approx(10.0)


def test_aggregate_strategy_rows_means():
    per_query = {
        "dynamic": [
            {
                "metrics": {"recall@10": 0.5, "ndcg@10": 0.4},
                "returned": 3,
                "tokens_estimate": 100.0,
                "latency_ms": 10.0,
            },
            {
                "metrics": {"recall@10": 0.7, "ndcg@10": 0.6},
                "returned": 5,
                "tokens_estimate": 200.0,
                "latency_ms": 20.0,
            },
        ]
    }
    rows = aggregate_strategy_rows(per_query)
    dynamic = [r for r in rows if r["strategy"] == "dynamic"][0]
    assert dynamic["recall@10"] == pytest.approx(0.6)
    assert dynamic["ndcg@10"] == pytest.approx(0.5)
    assert dynamic["avg_returned"] == pytest.approx(4.0)
    assert dynamic["avg_tokens"] == pytest.approx(150.0)
    assert dynamic["p95_latency_ms"] == pytest.approx(20.0)
