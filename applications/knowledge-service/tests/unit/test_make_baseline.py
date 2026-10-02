# -*- coding: utf-8 -*-
"""
test_make_baseline.py —— 脱敏基准锚点工具（Phase D 台账 baseline 侧）的纯函数 + 薄壳单测。

覆盖：
- sanitize_record：只保 qid/tags + 门禁所需数值，**丢弃 context/answer/reference/query/reasons**；
- generation.skipped → 仅保 skipped 标志，不落分数；缺指标键 → 只搬运存在的键；
- build_meta：sanitized=True + 溯源字段；
- main：从 raw per-query 产出 baselines/<label>/e2e_per_query.jsonl + meta；产物字节级**不含正文**；
  默认拒绝覆盖既有锚点（--overwrite 才覆盖）；
- 与 compare_runs 的互操作：脱敏产物仍能被 compare_runs 正常配对（功能等价于源 run）。

不连服务、不调 LLM，纯本地文件操作。
"""

import json
from pathlib import Path

from eval.compare_runs import load_per_query, paired_series
from eval.make_baseline import (
    build_meta,
    main,
    resolve_per_query,
    sanitize_record,
    sanitize_records,
)

FORBIDDEN_KEYS = {"context", "answer", "answer_len", "query", "reference", "item_name"}
# 正文里可能出现、须确保不泄漏进锚点的明文 token（模拟真实说明书正文）。
SECRET_MARKERS = ("观众人数", "说明书正文", "答案正文", "参考回答")


def _full_rec(qid="g001", **overrides):
    rec = {
        "qid": qid,
        "query": "什么是观众人数？",
        "item_name": "展品A",
        "tags": ["参数查询"],
        "context": "## 532 观众人数 说明书正文……",
        "reference": "参考回答：进入展览场所的观众数量。",
        "answer": "答案正文：观众人数指……",
        "answer_len": 42,
        "retrieval": {"metrics": {
            "recall@5": 1.0, "recall@10": 1.0, "mrr": 1.0,
            "hit_rate@5": 1.0, "ndcg@10": 0.85,
        }},
        "generation": {
            "faithfulness": 1.0, "relevance": 0.9, "correctness": 0.8,
            "reasons": {"faithfulness": "回答完全基于参考资料……"},
        },
    }
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------------------
# sanitize_record
# ---------------------------------------------------------------------------
def test_sanitize_keeps_only_gate_relevant_fields():
    out = sanitize_record(_full_rec())
    assert out["qid"] == "g001"
    assert out["tags"] == ["参数查询"]
    assert out["retrieval"]["metrics"]["ndcg@10"] == 0.85
    assert out["generation"]["faithfulness"] == 1.0
    # 正文类键一律不落
    assert FORBIDDEN_KEYS.isdisjoint(out.keys())
    assert "reasons" not in out["generation"]


def test_sanitize_generation_skipped_drops_dims():
    out = sanitize_record(_full_rec(generation={"skipped": True}))
    assert out["generation"] == {"skipped": True}


def test_sanitize_partial_metrics_only_present_keys():
    rec = _full_rec()
    rec["retrieval"]["metrics"] = {"ndcg@10": 0.5}
    out = sanitize_record(rec)
    assert out["retrieval"]["metrics"] == {"ndcg@10": 0.5}


def test_sanitize_records_length_preserved():
    assert len(sanitize_records([_full_rec(qid="a"), _full_rec(qid="b")])) == 2


# ---------------------------------------------------------------------------
# build_meta
# ---------------------------------------------------------------------------
def test_build_meta_fields():
    meta = build_meta("eval/runs/xxx/", "lbl", 60, None)
    assert meta["sanitized"] is True
    assert meta["label"] == "lbl"
    assert meta["n_records"] == 60
    assert meta["note"]  # 默认备注非空


# ---------------------------------------------------------------------------
# main（端到端薄壳）
# ---------------------------------------------------------------------------
def _write_raw(path: Path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_main_produces_sanitized_anchor(tmp_path: Path):
    raw = tmp_path / "src_run" / "e2e_per_query.jsonl"
    _write_raw(raw, [_full_rec(qid="g001"), _full_rec(qid="g002")])
    out_root = tmp_path / "baselines"
    rc = main(["--run", str(raw.parent), "--label", "anchor1", "--out-root", str(out_root)])
    assert rc == 0

    anchor = out_root / "anchor1" / "e2e_per_query.jsonl"
    assert anchor.exists()
    (out_root / "anchor1" / "baseline_meta.json").exists()

    # 字节级：脱敏产物不得含任何正文明文 / 正文键
    blob = anchor.read_text(encoding="utf-8")
    for marker in SECRET_MARKERS:
        assert marker not in blob, f"正文明文泄漏：{marker}"
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in blob, f"正文键泄漏：{key}"


def test_main_refuses_overwrite_without_flag(tmp_path: Path):
    raw = tmp_path / "src_run" / "e2e_per_query.jsonl"
    _write_raw(raw, [_full_rec()])
    out_root = tmp_path / "baselines"
    assert main(["--run", str(raw.parent), "--label", "anchor1", "--out-root", str(out_root)]) == 0
    # 第二次：未加 --overwrite → 拒绝
    assert main(["--run", str(raw.parent), "--label", "anchor1", "--out-root", str(out_root)]) == 1
    # 加 --overwrite → 通过
    assert main(["--run", str(raw.parent), "--label", "anchor1",
                 "--out-root", str(out_root), "--overwrite"]) == 0


def test_main_missing_source_returns_1(tmp_path: Path):
    assert main(["--run", str(tmp_path / "nope"), "--label", "x",
                 "--out-root", str(tmp_path / "b")]) == 1


def test_resolve_per_query_dir_vs_file(tmp_path: Path):
    d = tmp_path / "run"
    d.mkdir()
    assert resolve_per_query(str(d)).name == "e2e_per_query.jsonl"
    fp = d / "e2e_per_query.jsonl"
    assert resolve_per_query(str(fp)) == fp


# ---------------------------------------------------------------------------
# 与 compare_runs 互操作（证明脱敏锚点功能等价，门禁照跑不误）
# ---------------------------------------------------------------------------
def test_sanitized_anchor_is_consumable_by_compare_runs(tmp_path: Path):
    raw = tmp_path / "src_run" / "e2e_per_query.jsonl"
    _write_raw(raw, [
        _full_rec(qid="g001"),
        _full_rec(qid="g002", retrieval={"metrics": {
            "recall@5": 0.5, "recall@10": 0.6, "mrr": 0.55,
            "hit_rate@5": 0.5, "ndcg@10": 0.58}}),
    ])
    out_root = tmp_path / "baselines"
    assert main(["--run", str(raw.parent), "--label", "anchor", "--out-root", str(out_root)]) == 0

    anchor = load_per_query(out_root / "anchor" / "e2e_per_query.jsonl")
    src = load_per_query(raw)
    # 用脱敏锚点 vs 原始 run 配对：ndcg@10 应取到全部 2 条有效配对（数值未失真）
    bs, cs, qids = paired_series(anchor, src, "ndcg@10")
    assert set(qids) == {"g001", "g002"}
    assert sorted(bs) == sorted(cs)  # 脱敏后数值与源一致
