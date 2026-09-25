"""agent_core.metrics.retrieval 单元测试。"""

import pytest

from agent_core.metrics.retrieval import (
    compute_retrieval_metrics,
    dcg_at_k,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


def test_recall_full_hit():
    assert recall_at_k(["a", "b", "c"], ["a", "c"], k=5) == 1.0


def test_recall_partial_hit():
    assert recall_at_k(["a", "b"], ["a", "c"], k=5) == 0.5


def test_recall_empty_relevant():
    assert recall_at_k(["a", "b"], [], k=5) == 0.0


def test_recall_k_cutoff():
    assert recall_at_k(["a", "b", "c"], ["c"], k=2) == 0.0


def test_hit_rate_hit():
    assert hit_rate_at_k(["a", "b", "c"], ["b"], k=3) == 1.0


def test_hit_rate_miss():
    assert hit_rate_at_k(["a", "b"], ["c"], k=2) == 0.0


def test_mrr_first_position():
    assert mrr(["a", "b", "c"], ["a"]) == 1.0


def test_mrr_third_position():
    assert mrr(["x", "y", "a"], ["a"]) == pytest.approx(1 / 3)


def test_mrr_no_match():
    assert mrr(["x", "y"], ["a"]) == 0.0


def test_dcg_basic():
    scores = [3, 2, 1]
    result = dcg_at_k(scores)
    expected = 3 / 1 + 2 / 1.5849625 + 1 / 2.0
    assert result == pytest.approx(expected, rel=1e-4)


def test_ndcg_perfect_ranking():
    retrieved = ["a", "b"]
    relevant = ["a", "b"]
    grades = {"a": 2, "b": 1}
    assert ndcg_at_k(retrieved, relevant, grades, k=10) == pytest.approx(1.0)


def test_ndcg_bad_ranking():
    retrieved = ["c", "b", "a"]
    relevant = ["a", "b"]
    grades = {"a": 2, "b": 1, "c": 0}
    result = ndcg_at_k(retrieved, relevant, grades, k=10)
    assert 0 < result < 1.0


def test_compute_retrieval_metrics_keys():
    metrics = compute_retrieval_metrics(["a", "b"], ["a"], grades={"a": 2})
    assert set(metrics.keys()) == {"recall@5", "recall@10", "mrr", "hit_rate@5", "ndcg@10"}
    assert metrics["recall@5"] == 1.0
    assert metrics["mrr"] == 1.0
