# -*- coding: utf-8 -*-
"""
test_run_e2e_eval.py —— 端到端运行器的纯报表/聚合助手单测（不连 Milvus/LLM）。

run_e2e_eval 顶层只导入纯 stdlib（scorers/ablation），重依赖惰性加载，故可安全导入其纯函数。
覆盖：
- _generation_bucket_summary：按 tag 分桶生成层得分（skip/None 不计入）；
- _render_report：检索层/生成层**分离**呈现；生成层 skipped 时诚实标注、不拿空值冒充。
"""

from types import SimpleNamespace

from eval.run_e2e_eval import _generation_bucket_summary, _render_report


def _args(scorer="judge"):
    return SimpleNamespace(scorer=scorer, enable_hyde=False, skip_rerank=False, max_context_chars=6000)


def test_generation_bucket_summary_groups_by_tag():
    records = [
        {"tags": ["参数查询"], "generation": {"faithfulness": 1.0, "relevance": 0.5, "correctness": 0.5}},
        {"tags": ["参数查询", "多跳"], "generation": {"faithfulness": 0.0, "relevance": None, "correctness": None}},
    ]
    b = _generation_bucket_summary(records)
    assert set(b) == {"参数查询", "多跳"}
    # relevance None 不计入 → 参数查询桶有效样本仅 1
    assert b["参数查询"]["relevance"]["n"] == 1
    assert b["参数查询"]["correctness"]["n"] == 1
    # 多跳桶仅 rec2：faithfulness 0.0 有效计入（非 None），correctness None → 不计
    assert b["多跳"]["faithfulness"]["mean"] == 0.0 and b["多跳"]["faithfulness"]["n"] == 1
    assert b["多跳"]["correctness"]["mean"] is None and b["多跳"]["correctness"]["n"] == 0


def test_render_report_separates_layers_and_flags_generation_skip():
    retrieval_overall = {"recall@5": 0.4, "recall@10": 0.6, "mrr": 0.5, "hit_rate@5": 0.7, "ndcg@10": 0.55}
    md = _render_report(
        "runX",
        "hashX",
        "eval_rag_routes",
        "golden.real.jsonl",
        10,
        _args(),
        retrieval_overall,
        {},
        {},
        {},
        gen_skipped=True,
        gen_skip_reason="LLM 客户端不可用",
    )
    assert "检索层" in md and "生成层" in md
    assert "0.55" in md  # 检索数字落地
    assert "生成层未评测" in md and "LLM 客户端不可用" in md
    assert "归因分离" in md


def test_render_report_generation_values_when_present():
    generation_overall = {
        "faithfulness": {"mean": 0.83, "n": 6},
        "relevance": {"mean": 0.7, "n": 6},
        "correctness": {"mean": None, "n": 0},
    }
    md = _render_report(
        "runY", "hashY", "c", "g", 6, _args("heuristic"),
        {"recall@5": 0.4, "recall@10": 0.6, "mrr": 0.5, "hit_rate@5": 0.7, "ndcg@10": 0.55},
        {}, generation_overall, {}, gen_skipped=False, gen_skip_reason="",
    )
    assert "0.83" in md and "faithfulness" in md
    # correctness 全 None → 均值 None（诚实，不显示为 0）
    assert "None" in md
