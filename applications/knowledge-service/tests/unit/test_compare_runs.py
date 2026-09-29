# -*- coding: utf-8 -*-
"""
test_compare_runs.py —— Phase D 回归门禁比较器的纯函数单测（不连服务）。

compare_runs 顶层只导入 stdlib + agent_core.metrics.compare（配对 bootstrap），
故可安全导入其逻辑。覆盖：
- extract_metric：检索取值 / 生成 skip→None / 缺字段→None；
- paired_series：按 qid 对齐、剔除单侧缺值；
- compare_metric：显著改进 / 显著回归 / 噪声内(CI含0) / 样本不足 / 无配对(n/a) 五判定；
- regressions / render_compare：核心指标回归筛选 + 报告结构与诚实 n/a；
- main：--fail-on-regression 在注入回归时非 0 退出、无回归时 0（端到端薄壳）。

bootstrap 用恒定差值构造 → CI 退化为点值、显著性确定，测试不依赖随机。
"""

import json
from pathlib import Path

from eval.compare_runs import (
    compare_metric,
    extract_metric,
    load_per_query,
    main,
    paired_series,
    regressions,
    render_compare,
    resolve_per_query,
)


def _rec(qid, ndcg=None, faith=None, gen_skipped=False):
    generation = {"skipped": True} if gen_skipped else {"faithfulness": faith}
    return {
        "qid": qid,
        "retrieval": {"metrics": {"ndcg@10": ndcg}},
        "generation": generation,
    }


# ---------------------------------------------------------------------------
# extract_metric
# ---------------------------------------------------------------------------
def test_extract_metric_retrieval_generation_and_skip():
    assert extract_metric(_rec("q1", ndcg=0.7), "ndcg@10") == 0.7
    assert extract_metric(_rec("q1", faith=1.0), "faithfulness") == 1.0
    # 生成层 skipped → None（不参与配对，不伪造）
    assert extract_metric(_rec("q1", gen_skipped=True, faith=1.0), "faithfulness") is None
    # 缺字段 → None
    assert extract_metric(_rec("q1"), "recall@10") is None


# ---------------------------------------------------------------------------
# paired_series
# ---------------------------------------------------------------------------
def test_paired_series_aligns_and_drops_missing():
    base = {"q1": _rec("q1", ndcg=0.5), "q2": _rec("q2", ndcg=0.6), "q3": _rec("q3", ndcg=None)}
    cand = {"q1": _rec("q1", ndcg=0.7), "q2": _rec("q2", ndcg=None), "q4": _rec("q4", ndcg=0.9)}
    bs, cs, qids = paired_series(base, cand, "ndcg@10")
    # 仅 q1 双方都有效值（q2 cand 缺、q3 base 缺、q4 无交集）
    assert qids == ["q1"]
    assert bs == [0.5] and cs == [0.7]


# ---------------------------------------------------------------------------
# compare_metric（五判定）
# ---------------------------------------------------------------------------
def _mk(base_vals, cand_vals, key="ndcg@10"):
    base = {f"q{i}": _rec(f"q{i}", ndcg=v) for i, v in enumerate(base_vals)}
    cand = {f"q{i}": _rec(f"q{i}", ndcg=v) for i, v in enumerate(cand_vals)}
    return base, cand


def test_compare_metric_significant_improvement():
    base, cand = _mk([0.5] * 8, [0.9] * 8)
    r = compare_metric(base, cand, "ndcg@10", confidence=0.95, seed=0, min_paired=5,
                       core_keys=("ndcg@10",))
    assert r["n"] == 8 and r["significant"] is True
    assert r["mean_diff"] > 0 and r["verdict"] == "显著改进"


def test_compare_metric_significant_regression():
    base, cand = _mk([0.9] * 8, [0.5] * 8)
    r = compare_metric(base, cand, "ndcg@10", confidence=0.95, seed=0, min_paired=5,
                       core_keys=("ndcg@10",))
    assert r["mean_diff"] < 0 and r["significant"] is True
    assert r["verdict"] == "显著回归"


def test_compare_metric_noise_within_ci():
    base, cand = _mk([0.6] * 8, [0.6] * 8)  # 恒等 → CI 含 0
    r = compare_metric(base, cand, "ndcg@10", confidence=0.95, seed=0, min_paired=5,
                       core_keys=("ndcg@10",))
    assert r["significant"] is False and r["verdict"] == "无显著变化"


def test_compare_metric_insufficient_samples():
    base, cand = _mk([0.5, 0.5], [0.9, 0.9])  # n=2 < min_paired
    r = compare_metric(base, cand, "ndcg@10", confidence=0.95, seed=0, min_paired=5,
                       core_keys=("ndcg@10",))
    assert r["n"] == 2 and r["verdict"] == "样本不足"


def test_compare_metric_no_paired_is_na():
    base, cand = _mk([0.5, 0.6], [None, None])
    r = compare_metric(base, cand, "ndcg@10", confidence=0.95, seed=0, min_paired=5,
                       core_keys=("ndcg@10",))
    assert r["n"] == 0 and r["verdict"] == "n/a"


# ---------------------------------------------------------------------------
# regressions / render_compare
# ---------------------------------------------------------------------------
def test_regressions_filters_only_core_significant():
    results = [
        {"key": "ndcg@10", "core": True, "verdict": "显著回归", "mean_diff": -0.1, "ci_low": -0.2, "ci_high": -0.05},
        {"key": "mrr", "core": False, "verdict": "显著回归", "mean_diff": -0.1, "ci_low": -0.2, "ci_high": -0.05},
        {"key": "faithfulness", "core": True, "verdict": "无显著变化", "mean_diff": -0.01, "ci_low": -0.05, "ci_high": 0.03},
    ]
    bad = regressions(results)
    # 仅核心 + 显著回归命中（mrr 非核心、faithfulness 噪声内均排除）
    assert [r["key"] for r in bad] == ["ndcg@10"]


def test_render_compare_structure_and_na():
    results = [
        {"key": "ndcg@10", "core": True, "n": 8, "mean_diff": -0.1, "ci_low": -0.2, "ci_high": -0.05,
         "significant": True, "verdict": "显著回归"},
        {"key": "faithfulness", "core": True, "n": 0, "mean_diff": None, "ci_low": None, "ci_high": None,
         "significant": False, "verdict": "n/a"},
    ]
    md = render_compare("baseA", "candB", results, 0.95)
    assert "baseline vs candidate" in md
    assert "显著回归" in md and "n/a" in md
    assert "显著回归的核心指标：**1**" in md
    assert "门禁不通过" in md


# ---------------------------------------------------------------------------
# main 薄壳（注入回归 → 非 0；无回归 → 0）
# ---------------------------------------------------------------------------
def _write_jsonl(path: Path, recs):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")


def _records_with_ndcg(vals):
    return [_rec(f"q{i}", ndcg=v, faith=1.0) for i, v in enumerate(vals)]


def test_main_flags_regression(tmp_path: Path):
    base = tmp_path / "base.jsonl"
    cand = tmp_path / "cand.jsonl"
    _write_jsonl(base, _records_with_ndcg([0.9] * 8))
    _write_jsonl(cand, _records_with_ndcg([0.5] * 8))  # 注入 ndcg@10 显著回归
    code = main([
        "--baseline", str(base), "--candidate", str(cand),
        "--core", "ndcg@10", "--fail-on-regression",
    ])
    assert code == 1


def test_main_passes_when_no_regression(tmp_path: Path):
    base = tmp_path / "base.jsonl"
    cand = tmp_path / "cand.jsonl"
    _write_jsonl(base, _records_with_ndcg([0.6] * 8))
    _write_jsonl(cand, _records_with_ndcg([0.7] * 8))  # 改进，不拦门
    code = main([
        "--baseline", str(base), "--candidate", str(cand),
        "--core", "ndcg@10", "--fail-on-regression",
    ])
    assert code == 0


def test_resolve_per_query_dir_and_file(tmp_path: Path):
    run_dir = tmp_path / "runX"
    run_dir.mkdir()
    assert resolve_per_query(str(run_dir)) == run_dir / "e2e_per_query.jsonl"
    direct = tmp_path / "custom.jsonl"
    assert resolve_per_query(str(direct)) == direct


def test_load_per_query_indexes_by_qid(tmp_path: Path):
    p = tmp_path / "e2e_per_query.jsonl"
    _write_jsonl(p, [_rec("q1", ndcg=0.5), _rec("q2", ndcg=0.6)])
    got = load_per_query(p)
    assert set(got) == {"q1", "q2"}
    assert got["q1"]["retrieval"]["metrics"]["ndcg@10"] == 0.5
