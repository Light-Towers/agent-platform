# -*- coding: utf-8 -*-
"""
test_scorers.py —— 端到端 scorer 协议纯函数单测（零 LLM/Milvus）。

覆盖 eval/scorers.py：
- token F1 / 接地度（词面 faithfulness 代理）边界与不猜高分约定；
- judge 档位归一（0/1/2→0/0.5/1）与越界/非法→None；
- 上下文组装截断；
- HeuristicScorer 缺 reference → correctness None（不伪造）；
- aggregate_scores 跳过 None/skipped、全无效→mean None；
- make_scorer 未知名报错。
"""

import pytest

from eval.scorers import (
    HeuristicScorer,
    aggregate_scores,
    build_context,
    default_answer_prompt,
    grounding_ratio,
    judge_prompt,
    make_scorer,
    normalize_grade,
    token_f1,
)


def test_token_f1_bounds():
    assert token_f1("", "x") == 0.0
    assert token_f1("额定电压 220V", "额定电压 220V") == 1.0
    assert 0.0 < token_f1("额定电压是多少", "额定电压 220V 功率") < 1.0


def test_grounding_ratio_penalizes_hallucination():
    ctx = "HAK 180 烫金机额定电压 220V 功率 1.5kW"
    grounded = "额定电压是 220V"
    halluc = "额定电压是 380V 且支持蓝牙"
    assert grounding_ratio(grounded, ctx) > grounding_ratio(halluc, ctx)
    assert grounding_ratio("", ctx) == 0.0


def test_normalize_grade():
    assert normalize_grade(0) == 0.0
    assert normalize_grade(1) == 0.5
    assert normalize_grade(2) == 1.0
    assert normalize_grade("2") == 1.0
    assert normalize_grade(3) is None  # 越界不猜
    assert normalize_grade("abc") is None


def test_build_context_truncates():
    docs = [{"content": "A" * 100}, {"content": "B" * 100}]
    ctx = build_context(docs, max_chars=150)
    assert len(ctx) <= 150
    assert build_context([], max_chars=10) == ""


def test_build_context_reads_text_field_variants():
    docs = [{"text": "正文1"}, {"snippet": "摘要2"}]
    ctx = build_context(docs, max_chars=100)
    assert "正文1" in ctx and "摘要2" in ctx


def test_heuristic_scorer_shape():
    s = HeuristicScorer()
    out = s.score(query="额定电压多少", context="额定电压 220V", answer="220V", reference="220V")
    assert set(out) >= {"faithfulness", "relevance", "correctness", "reasons"}
    assert out["correctness"] is not None
    # 缺 reference → correctness None（不伪造）
    out2 = s.score(query="q", context="c", answer="a", reference=None)
    assert out2["correctness"] is None


def test_aggregate_skips_none_and_empty():
    records = [
        {"faithfulness": 1.0, "relevance": 0.5, "correctness": None},
        {"faithfulness": 0.0, "relevance": 0.5, "correctness": None},
        {"faithfulness": None, "relevance": None, "correctness": None, "skipped": True},
    ]
    agg = aggregate_scores(records)
    assert agg["faithfulness"]["n"] == 2 and agg["faithfulness"]["mean"] == 0.5
    assert agg["correctness"]["mean"] is None and agg["correctness"]["n"] == 0


def test_make_scorer_unknown_raises():
    with pytest.raises(ValueError):
        make_scorer("nope")
    assert make_scorer("heuristic").name == "heuristic"


def test_prompts_are_transparent_and_grounded():
    ap = default_answer_prompt(query="额定电压多少", context="220V", item_name="HAK 180")
    assert "仅依据" in ap and "HAK 180" in ap and "220V" in ap
    # 上下文含花括号也不炸（纯 f-string，无 str.format）
    ap2 = default_answer_prompt(query="q", context="含 {json} 花括号", item_name="")
    assert "{json}" in ap2
    jp = judge_prompt(query="q", context="c", answer="a", reference="r")
    assert "faithfulness" in jp and "correctness" in jp and "r" in jp
