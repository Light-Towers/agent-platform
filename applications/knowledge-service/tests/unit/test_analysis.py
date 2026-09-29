# -*- coding: utf-8 -*-
"""
test_analysis.py —— 数据源边际贡献归因编排单测（纯函数，无外部服务）。

覆盖 eval/analysis.py：
- leave_one_out / add_one_in 的差值方向与判定文案；
- 显著性缺失（不显著）判为中性/冗余，不把噪声渲染成"更优"；
- 长度不齐 / 缺失指标的格子被跳过（不伪造）；
- 非法 mode 抛 ValueError。
"""

import pytest

from eval.analysis import bucket_slice, contribution_rows, summarize_rows

_N = 6


def test_leave_one_out_positive_contribution():
    # 完整融合每 query 0.9，去掉 kg 后掉到 0.5 → kg 有正贡献（去掉变差）
    base = {"ndcg@10": [0.9] * _N}
    variants = {"loo:kg": {"ndcg@10": [0.5] * _N}}
    rows = contribution_rows(base, variants, mode="leave_one_out", metric_keys=["ndcg@10"], seed=1)
    assert len(rows) == 1
    r = rows[0]
    assert r["mean_diff"] == pytest.approx(0.4)
    assert r["significant"] is True
    assert "正贡献" in r["verdict"]


def test_leave_one_out_drag():
    # 去掉 kg 反而涨分 → kg 拖后腿
    base = {"ndcg@10": [0.5] * _N}
    variants = {"loo:kg": {"ndcg@10": [0.9] * _N}}
    rows = contribution_rows(base, variants, mode="leave_one_out", metric_keys=["ndcg@10"], seed=1)
    assert "拖后腿" in rows[0]["verdict"]


def test_add_one_in_gain():
    # emb_only 0.5 → +hyde 0.9 → 叠加有增益
    base = {"recall@10": [0.5] * _N}
    variants = {"emb+hyde": {"recall@10": [0.9] * _N}}
    rows = contribution_rows(base, variants, mode="add_one_in", metric_keys=["recall@10"], seed=1)
    assert rows[0]["mean_diff"] == pytest.approx(0.4)
    assert "增益" in rows[0]["verdict"]


def test_identical_is_neutral_not_significant():
    seq = [0.6, 0.7, 0.5, 0.65, 0.55, 0.72]
    base = {"ndcg@10": seq}
    variants = {"loo:hyde": {"ndcg@10": list(seq)}}
    rows = contribution_rows(base, variants, mode="leave_one_out", metric_keys=["ndcg@10"], seed=1)
    assert rows[0]["significant"] is False
    assert "冗余" in rows[0]["verdict"] or "中性" in rows[0]["verdict"]


def test_mismatched_length_is_skipped():
    base = {"ndcg@10": [0.9] * _N}
    variants = {"loo:kg": {"ndcg@10": [0.5] * (_N - 1)}}  # 少一条 → 不可比
    rows = contribution_rows(base, variants, mode="leave_one_out", metric_keys=["ndcg@10"])
    assert rows == []


def test_missing_metric_key_is_skipped():
    base = {"ndcg@10": [0.9] * _N}
    variants = {"loo:kg": {"recall@10": [0.5] * _N}}  # 无 ndcg@10
    rows = contribution_rows(base, variants, mode="leave_one_out", metric_keys=["ndcg@10"])
    assert rows == []


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        contribution_rows({"ndcg@10": [0.9]}, {"x": {"ndcg@10": [0.5]}}, mode="bogus", metric_keys=["ndcg@10"])


def test_summarize_rows_counts_by_verdict():
    rows = [
        {"metric": "ndcg@10", "verdict": "正贡献(去掉变差)"},
        {"metric": "ndcg@10", "verdict": "拖后腿(去掉变好)"},
        {"metric": "ndcg@10", "verdict": "冗余/噪声"},
    ]
    counts = summarize_rows(rows, metric_key="ndcg@10")
    assert counts["增益/正贡献"] == 1
    assert counts["有害/拖后腿"] == 1
    assert counts["中性/冗余"] == 1


def test_bucket_slice_filters_by_bucket_and_skip():
    per_query = [
        {"tag": "参数查询", "configs": {"emb_only": {"metrics": {"ndcg@10": 0.9}, "skipped": False}}},
        {"tag": "多跳", "configs": {"emb_only": {"metrics": {"ndcg@10": 0.3}, "skipped": False}}},
        {"tag": "参数查询", "configs": {"emb_only": {"metrics": {"ndcg@10": 0.0}, "skipped": True}}},
    ]
    vals = bucket_slice(per_query, "tag", "参数查询", "emb_only", "ndcg@10")
    assert vals == [0.9]  # skipped 那条被剔除，另一桶不计入
