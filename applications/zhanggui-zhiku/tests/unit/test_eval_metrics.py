# -*- coding: utf-8 -*-
"""
test_eval_metrics.py —— 检索评测指标纯函数单测（M2，方案 §6.2 / §2.4）。

覆盖 eval/metrics.py 的 Recall@K / MRR / HitRate@K / nDCG@K：
- 已知排序的 fixture 断言数值正确；
- 边界：空召回、空相关、全相关；
- **nDCG 排序敏感性**：同样一组相关块，"好排序"的 nDCG 必须显著高于"坏排序"，
  这是"排序好坏能拉开分差"的核心用例（二值指标无法体现）。

【不依赖重型依赖】：本文件只 import eval.metrics（纯 python + math），
可在纯 pytest 环境运行（与 tests/unit 其余用例一致）。
"""

import math

import pytest

from eval.metrics import (
    compute_retrieval_metrics,
    dcg_at_k,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


# ---------------------------------------------------------------------------
# Recall@K
# ---------------------------------------------------------------------------
def test_recall_at_k_full_hit_within_topk():
    # 5 个相关全部落在 Top5 内 → Recall@5 = 1.0
    assert recall_at_k(["a", "b", "c", "d", "e"], ["a", "c", "e"], 5) == pytest.approx(1.0)


def test_recall_at_k_partial_hit():
    # Top5 命中 2/4 → 0.5
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = ["a", "c", "f", "g"]
    assert recall_at_k(retrieved, relevant, 5) == pytest.approx(0.5)


def test_recall_at_k_top1_misses_relevant_at_rank2():
    # k=1 时只取第一位；相关块在第 2 位 → Recall@1 = 0
    assert recall_at_k(["b", "a"], ["a"], 1) == pytest.approx(0.0)


def test_recall_at_k_empty_relevant_returns_zero():
    assert recall_at_k(["a", "b"], [], 5) == pytest.approx(0.0)


def test_recall_at_k_empty_retrieved_returns_zero():
    assert recall_at_k([], ["a"], 5) == pytest.approx(0.0)


def test_recall_at_k_nonpositive_k_returns_zero():
    assert recall_at_k(["a", "b"], ["a"], 0) == pytest.approx(0.0)
    assert recall_at_k(["a", "b"], ["a"], -1) == pytest.approx(0.0)


def test_recall_at_k_truncates_to_k():
    # 相关块在第 6 位，k=5 看不到 → 0；k=10 能看到 → 命中
    retrieved = ["x1", "x2", "x3", "x4", "x5", "rel"]
    assert recall_at_k(retrieved, ["rel"], 5) == pytest.approx(0.0)
    assert recall_at_k(retrieved, ["rel"], 10) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# HitRate@K
# ---------------------------------------------------------------------------
def test_hit_rate_at_k_hit():
    assert hit_rate_at_k(["a", "b"], ["b"], 5) == pytest.approx(1.0)


def test_hit_rate_at_k_miss():
    assert hit_rate_at_k(["a", "b"], ["c"], 5) == pytest.approx(0.0)


def test_hit_rate_at_k_empty_relevant_returns_zero():
    assert hit_rate_at_k(["a", "b"], [], 5) == pytest.approx(0.0)


def test_hit_rate_at_k_outside_topk():
    # 相关块在第 6 位，k=5 → 0
    assert hit_rate_at_k(["x1", "x2", "x3", "x4", "x5", "rel"], ["rel"], 5) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# MRR
# ---------------------------------------------------------------------------
def test_mrr_first_relevant_at_rank1():
    assert mrr(["a", "b", "c"], ["a"]) == pytest.approx(1.0)


def test_mrr_first_relevant_at_rank2():
    assert mrr(["a", "b", "c"], ["b"]) == pytest.approx(0.5)


def test_mrr_no_relevant_returns_zero():
    assert mrr(["a", "b"], ["c"]) == pytest.approx(0.0)


def test_mrr_empty_retrieved_returns_zero():
    assert mrr([], ["a"]) == pytest.approx(0.0)


def test_mrr_takes_first_occurrence():
    # 相关块出现在 rank2 与 rank5 → MRR 只看第一个 = 1/2
    assert mrr(["a", "rel1", "b", "c", "rel2"], ["rel1", "rel2"]) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# DCG@K
# ---------------------------------------------------------------------------
def test_dcg_at_k_known_values():
    # DCG = 3/log2(2) + 2/log2(3) + 3/log2(4) + 0 + 1/log2(6) + 2/log2(7)
    scores = [3, 2, 3, 0, 1, 2]
    expected = 3 / math.log2(2) + 2 / math.log2(3) + 3 / math.log2(4) + 0 + 1 / math.log2(6) + 2 / math.log2(7)
    assert dcg_at_k(scores, k=6) == pytest.approx(expected)


def test_dcg_at_k_respects_k():
    scores = [3, 2, 3, 0, 1, 2]
    # k=3 只取前三项：3/log2(2) + 2/log2(3) + 3/log2(4)
    expected = 3 / math.log2(2) + 2 / math.log2(3) + 3 / math.log2(4)
    assert dcg_at_k(scores, k=3) == pytest.approx(expected)


def test_dcg_at_k_empty_returns_zero():
    assert dcg_at_k([], k=10) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# nDCG@K（核心：分级相关性 + 排序敏感性）
# ---------------------------------------------------------------------------
def test_ndcg_at_k_perfect_order_is_one():
    # 检索返回顺序恰好是理想顺序（2 分在前、1 分在后、0 分垫底）→ nDCG@10 = 1.0
    retrieved = ["a", "b", "c"]
    grades = {"a": 2, "b": 1, "c": 0}
    assert ndcg_at_k(retrieved, ["a", "b", "c"], grades, k=10) == pytest.approx(1.0)


def test_ndcg_at_k_poor_order_is_lower_than_perfect():
    # 同一组相关块，只是顺序变差（1 分跑到 2 分前面）→ nDCG 显著下降
    grades = {"a": 2, "b": 1, "c": 0}
    perfect = ndcg_at_k(["a", "b", "c"], ["a", "b", "c"], grades, k=10)
    poor = ndcg_at_k(["b", "a", "c"], ["a", "b", "c"], grades, k=10)
    assert perfect == pytest.approx(1.0)
    assert poor < perfect
    # 数值口径：DCG = 1/log2(2) + 2/log2(3)；IDCG = 2/log2(2) + 1/log2(3)
    expected_poor = (1 / math.log2(2) + 2 / math.log2(3)) / (2 / math.log2(2) + 1 / math.log2(3))
    assert poor == pytest.approx(expected_poor)


def test_ndcg_at_k_relevant_not_retrieved_returns_zero():
    # 期望块完全没召回 → 无增益，nDCG = 0
    retrieved = ["y", "z"]
    grades = {"x": 2}
    assert ndcg_at_k(retrieved, ["x"], grades, k=10) == pytest.approx(0.0)


def test_ndcg_at_k_empty_retrieved_returns_zero():
    grades = {"a": 2}
    assert ndcg_at_k([], ["a"], grades, k=10) == pytest.approx(0.0)


def test_ndcg_at_k_no_positive_grade_returns_zero():
    # grade 全为 0（不相关）→ 无正分级 → nDCG 无意义，返回 0
    grades = {"a": 0}
    assert ndcg_at_k(["a"], ["a"], grades, k=10) == pytest.approx(0.0)


def test_ndcg_at_k_grades_drive_relevance_even_with_empty_relevant_list():
    # relevant_chunk_ids 可为空，但 grade 分级仍能驱动 nDCG（golden 标注灵活性）
    retrieved = ["a", "b"]
    grades = {"a": 2, "b": 1}
    assert ndcg_at_k(retrieved, [], grades, k=10) == pytest.approx(1.0)


def test_ndcg_at_k_handles_int_and_str_ids():
    # Milvus 主键可能为 int，golden 标注可能为 str：两种 id 应能正确匹配
    retrieved = [101, 102]
    grades = {101: 2, 102: 1}
    assert ndcg_at_k(retrieved, ["101", "102"], grades, k=10) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_retrieval_metrics 集成
# ---------------------------------------------------------------------------
def test_compute_retrieval_metrics_known_fixture():
    retrieved = ["c_1", "c_2", "c_3", "c_4", "c_5", "c_6"]
    relevant = ["c_2", "c_4", "c_7"]
    grades = {"c_2": 2, "c_4": 1, "c_7": 2}
    metrics = compute_retrieval_metrics(retrieved, relevant, grades)

    # recall@5 / @10：命中 c_2、c_4（共 3 个相关中的 2 个）
    assert metrics["recall@5"] == pytest.approx(2 / 3)
    assert metrics["recall@10"] == pytest.approx(2 / 3)
    # MRR：第一个相关块在 rank 2
    assert metrics["mrr"] == pytest.approx(0.5)
    # HitRate@5：Top5 内有相关块
    assert metrics["hit_rate@5"] == pytest.approx(1.0)
    # nDCG@10：DCG = 2/log2(3) + 1/log2(5)；IDCG = 2/log2(2) + 2/log2(3) + 1/log2(4)
    expected_ndcg = (2 / math.log2(3) + 1 / math.log2(5)) / (2 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4))
    assert metrics["ndcg@10"] == pytest.approx(expected_ndcg)


def test_compute_retrieval_metrics_all_empty():
    metrics = compute_retrieval_metrics([], [], {})
    assert metrics["recall@5"] == 0.0
    assert metrics["recall@10"] == 0.0
    assert metrics["mrr"] == 0.0
    assert metrics["hit_rate@5"] == 0.0
    assert metrics["ndcg@10"] == 0.0
