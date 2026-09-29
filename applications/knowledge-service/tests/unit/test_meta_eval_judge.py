# -*- coding: utf-8 -*-
"""
test_meta_eval_judge.py —— Phase C2 judge 选型 meta-eval 的纯函数单测（不连 LLM/服务）。

meta_eval_judge 顶层只导入纯 stdlib + agent-core 统计原语（scorers/ablation 皆惰性），
故可安全导入其纯逻辑。覆盖：
- to_bucket：0..1 → 0/1/2 分箱与越界钳位、None 透传；
- agreement_metrics：缺标剔除、κ/ρ 计算、样本 <2 全 None（不猜显著性）；
- direct_requires：self→0、未安装→None（n/a，不伪造）；
- make_candidate_scorer：self 可用、未安装包 available False；
- decide：五种决策分支（无候选/无标注/self 最优/噪声内取自研/外部显著胜出）；   
- render_judge_selection：四维表结构 + 未安装诚实标注；
- export/load 裁决集模板往返；
- 路径 3（AI 交叉一致性）：agreement_symmetric + pairwise_agreement + decide_cross_agreement
  三分支（收敛/离群/未收敛） + render/run_mode3 端到端（monkeypatch 桩候选，不连 LLM）。
"""

import json
from pathlib import Path

from eval.meta_eval_judge import (
    agreement_metrics,
    agreement_symmetric,
    decide,
    decide_cross_agreement,
    direct_requires,
    export_adjudication_template,
    load_adjudication,
    make_candidate_scorer,
    pairwise_agreement,
    render_cross_agreement,
    render_judge_selection,
    run_mode3_cross_agreement,
    score_records_for_candidate,
    to_bucket,
)


# ---------------------------------------------------------------------------
# to_bucket
# ---------------------------------------------------------------------------
def test_to_bucket_boundaries_and_clamp():
    assert to_bucket(None) is None
    assert to_bucket(0.0) == 0
    assert to_bucket(0.5) == 1
    assert to_bucket(1.0) == 2
    # 越界钳位（防上游偶发 <0 / >1）
    assert to_bucket(-0.3) == 0
    assert to_bucket(1.4) == 2


# ---------------------------------------------------------------------------
# agreement_metrics
# ---------------------------------------------------------------------------
def test_agreement_perfect_match():
    human = [0, 1, 2]
    model = [0.0, 0.5, 1.0]  # 分箱后与人工完全一致，原值同向
    m = agreement_metrics(human, model)
    assert m["n"] == 3
    assert m["kappa"] == 1.0
    assert m["spearman"] == 1.0


def test_agreement_drops_missing_labels():
    # 首条 human 缺标 → 剔除，仅在双方都有标的 3 条上算
    human = [None, 0, 1, 2]
    model = [0.5, 0.0, 0.5, 1.0]
    m = agreement_metrics(human, model)
    assert m["n"] == 3
    assert m["kappa"] == 1.0


def test_agreement_too_few_samples_returns_none():
    m = agreement_metrics([1], [0.5])
    assert m == {"kappa": None, "spearman": None, "n": 1}


# ---------------------------------------------------------------------------
# direct_requires
# ---------------------------------------------------------------------------
def test_direct_requires_self_and_missing():
    assert direct_requires(None) == 0  # 自研零额外依赖
    assert direct_requires("definitely_not_installed_pkg_xyz") is None  # 未安装 n/a，不猜


# ---------------------------------------------------------------------------
# make_candidate_scorer
# ---------------------------------------------------------------------------
def test_make_candidate_scorer_self_available():
    available, fn = make_candidate_scorer("self", llm=object())
    assert available is True
    assert callable(fn)


def test_make_candidate_scorer_uninstalled_unavailable():
    available, fn = make_candidate_scorer("totally_absent_pkg_abc")
    assert available is False
    assert fn is None


# ---------------------------------------------------------------------------
# decide（主判据 = faithfulness/correctness 平均 kappa）
# ---------------------------------------------------------------------------
def _row(candidate, kappa_f=None, kappa_c=None, available=True):
    ag = {}
    if kappa_f is not None:
        ag["faithfulness"] = {"kappa": kappa_f}
    if kappa_c is not None:
        ag["correctness"] = {"kappa": kappa_c}
    return {"candidate": candidate, "available": available, "agreement": ag}


def test_decide_no_available_falls_back_self():
    winner, reason = decide([_row("ragas", available=False)])
    assert winner == "self"
    assert "无任何候选" in reason


def test_decide_no_annotation_falls_back_self():
    # 可用但无人工一致性可算
    winner, reason = decide([_row("self")])
    assert winner == "self"
    assert "无人工一致性" in reason


def test_decide_self_is_best():
    results = [_row("self", 0.8, 0.8), _row("ragas", 0.6, 0.6)]
    winner, reason = decide(results)
    assert winner == "self"
    assert "最高" in reason


def test_decide_within_noise_prefers_self():
    # 外部略优但差异 0.03 ≤ 0.05（噪声内）→ 按 spec.md 取自研
    results = [_row("self", 0.70, 0.70), _row("ragas", 0.73, 0.73)]
    winner, reason = decide(results)
    assert winner == "self"
    assert "噪声内" in reason


def test_decide_external_significantly_better():
    results = [_row("self", 0.50, 0.50), _row("ragas", 0.85, 0.85)]
    winner, reason = decide(results)
    assert winner == "ragas"
    assert "不得固化进 pyproject" in reason


# ---------------------------------------------------------------------------
# render_judge_selection
# ---------------------------------------------------------------------------
def test_render_judge_selection_table_and_honesty():
    results = [
        {"candidate": "self", "available": True, "footprint": 0, "explainable": True,
         "agreement": {"faithfulness": {"kappa": 0.8, "spearman": 0.85},
                        "correctness": {"kappa": 0.7, "spearman": 0.8}},
         "cost": {"avg_tokens": 512.0, "avg_latency_ms": 900.0}},
        {"candidate": "ragas", "available": False, "footprint": None, "explainable": False,
         "agreement": {}, "cost": {"avg_tokens": None, "avg_latency_ms": None}},
    ]
    md = render_judge_selection(results, ("self", "自研一致性最高"), "30 条（候选：self, ragas）")
    assert "# Judge 选型决策备忘" in md
    assert "四维对比表" in md
    assert "0.8" in md and "0.85" in md
    # 未安装候选诚实标 ❌，footprint/cost 出 n/a 而非假数字
    assert "❌" in md and "n/a" in md
    assert "采用 `self`" in md


# ---------------------------------------------------------------------------
# export / load 裁决集模板往返
# ---------------------------------------------------------------------------
def test_export_and_load_adjudication_roundtrip(tmp_path: Path):
    per_query = tmp_path / "e2e_per_query.jsonl"
    rows = [
        {"qid": f"q{i}", "query": f"问题{i}", "context": f"上下文{i}",
         "answer": f"答案{i}", "reference": f"参考{i}"}
        for i in range(10)
    ]
    per_query.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    tmpl_path = tmp_path / "adjudication_template.jsonl"
    n = export_adjudication_template(per_query, tmpl_path, sample=5, seed=42)
    assert n == 5

    loaded = load_adjudication(tmpl_path)
    assert len(loaded) == 5
    for rec in loaded:
        # 模板态：human 档留空待人工填，上下文/答案/参考透传供标注
        assert rec["human"] == {"faithfulness": None, "correctness": None}
        assert rec["query"] and rec["answer"] is not None

    # 可复现：同 seed 重跑得到同一批
    tmpl2 = tmp_path / "template2.jsonl"
    export_adjudication_template(per_query, tmpl2, sample=5, seed=42)
    assert [r["qid"] for r in load_adjudication(tmpl2)] == [r["qid"] for r in loaded]


# ---------------------------------------------------------------------------
# 路径 3：AI 交叉一致性（纯函数）
# ---------------------------------------------------------------------------
def _score_map(pairs):
    return {q: {"faithfulness": f, "correctness": c} for q, (f, c) in pairs.items()}


def _self_outlier_maps():
    """self 与两个外部反向，外部之间完全一致 → 应判 self 离群。"""
    self_scores = {f"q{i}": (1.0 if i % 2 == 0 else 0.0, 1.0 if i % 2 == 0 else 0.0) for i in range(6)}
    ext_scores = {f"q{i}": (0.0 if i % 2 == 0 else 1.0, 0.0 if i % 2 == 0 else 1.0) for i in range(6)}
    return {
        "self": _score_map(self_scores),
        "ragas": _score_map(ext_scores),
        "deepeval": _score_map(ext_scores),
    }


def test_agreement_symmetric_identical_series_perfect():
    xs = [1.0, 1.0, 0.5, 0.5, 0.0, 0.0]
    r = agreement_symmetric(xs, xs)
    assert r["n"] == 6
    assert r["kappa"] == 1.0
    assert r["spearman"] == 1.0


def test_agreement_symmetric_drops_missing_pairs():
    r = agreement_symmetric([1.0, None, 0.5, 0.0], [1.0, 1.0, None, 0.0])
    assert r["n"] == 2  # 仅保留两边都非 None 的两对


def test_agreement_symmetric_too_few_returns_none():
    assert agreement_symmetric([1.0, None], [1.0, None]) == {"kappa": None, "spearman": None, "n": 1}


def test_pairwise_agreement_keys_sorted_no_self_pair():
    smaps = _self_outlier_maps()
    m = pairwise_agreement(smaps, ["self", "ragas", "deepeval"])
    # 对称、按名字字典序排，无对角。
    assert set(m.keys()) == {("deepeval", "self"), ("ragas", "self"), ("deepeval", "ragas")}
    for pair in m.values():
        assert set(pair.keys()) == {"faithfulness", "correctness"}


def test_decide_cross_only_self_returns_pending():
    d = decide_cross_agreement({}, ["self"])
    assert d[0] == "self"
    assert "无外部对比" in d[1]


def test_decide_cross_no_comparable_samples_fallback():
    # 有外部候选但矩阵无可用对→ 回退分支。
    d = decide_cross_agreement({}, ["self", "ragas", "deepeval"])
    assert d[0] == "self"
    assert "无可比对样本" in d[1]


def test_decide_cross_all_converged_keeps_self():
    same = {f"q{i}": (1.0 if i % 2 == 0 else 0.0, 1.0 if i % 2 == 0 else 0.0) for i in range(6)}
    smaps = {c: _score_map(same) for c in ["self", "ragas", "deepeval"]}
    m = pairwise_agreement(smaps, ["self", "ragas", "deepeval"])
    d = decide_cross_agreement(m, ["self", "ragas", "deepeval"], threshold=0.6)
    assert d[0] == "self"
    assert "判据收敛" in d[1]


def test_decide_cross_self_outlier_recommends_external():
    smaps = _self_outlier_maps()
    m = pairwise_agreement(smaps, ["self", "ragas", "deepeval"])
    d = decide_cross_agreement(m, ["self", "ragas", "deepeval"], threshold=0.6)
    assert d[0] == "external"
    assert "离群者" in d[1]


def test_decide_cross_all_divergent_signals_human_fallback():
    # 三方两两反向：self-外部 低、外部对也低 → 回退人工信号。
    a = {f"q{i}": (1.0 if i % 2 == 0 else 0.0, 1.0 if i % 2 == 0 else 0.0) for i in range(6)}
    b = {f"q{i}": (0.0 if i % 2 == 0 else 1.0, 0.0 if i % 2 == 0 else 1.0) for i in range(6)}
    c = {f"q{i}": (1.0 if (i % 3 == 0) else 0.0, 1.0 if (i % 3 == 0) else 0.0) for i in range(6)}
    smaps = {"self": _score_map(a), "ragas": _score_map(b), "deepeval": _score_map(c)}
    m = pairwise_agreement(smaps, ["self", "ragas", "deepeval"])
    d = decide_cross_agreement(m, ["self", "ragas", "deepeval"], threshold=0.6)
    # 不强行断言具体文案（取决于 κ 实际分布），只确保不往 “external” 误判。
    assert d[0] == "self"
    assert "external" not in d[1]


def test_score_records_unavailable_candidate_returns_empty():
    recs = [{"qid": "q1", "query": "", "context": "", "answer": "", "reference": ""}]
    assert score_records_for_candidate("pkg_obviously_not_installed", recs, llm=None) == {}


def test_render_cross_agreement_structure():
    smaps = _self_outlier_maps()
    m = pairwise_agreement(smaps, ["self", "ragas", "deepeval"])
    d = decide_cross_agreement(m, ["self", "ragas", "deepeval"])
    md = render_cross_agreement(["self", "ragas", "deepeval"], smaps, m, d, "6 条", 0.6)
    assert "路径 3" in md
    assert "决策" in md
    assert "| self |" in md and "| ragas |" in md and "| deepeval |" in md


def test_run_mode3_end_to_end_with_stubbed_scorer(tmp_path, monkeypatch):
    ds = tmp_path / "ds.jsonl"
    recs = [{"qid": f"q{i}", "query": "x", "context": "c", "answer": "a", "reference": "r"} for i in range(6)]
    ds.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")

    def _fake(candidate, llm=None):  # noqa: ARG001 —— 桩位，不真使 llm
        def _fn(rec, meter):  # noqa: ARG001
            i = int(rec["qid"][1:])
            if candidate == "self":
                v = 1.0 if i % 2 == 0 else 0.0
            else:
                v = 0.0 if i % 2 == 0 else 1.0
            return {"faithfulness": v, "correctness": v}
        return True, _fn

    monkeypatch.setattr("eval.meta_eval_judge.make_candidate_scorer", _fake)
    out = tmp_path / "judge_selection.md"
    rc = run_mode3_cross_agreement(ds, ["self", "ragas", "deepeval"], 0.6, out)
    assert rc == 0
    md = out.read_text(encoding="utf-8")
    assert "路径 3" in md
    # 外部两个同分、与 self 反向 → 应判 external
    assert "external" in md
