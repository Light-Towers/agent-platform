"""R1 漂移门禁逻辑单测（Plan-F Phase 2 P5）：save_baseline / compare_baseline 纯逻辑。

不依赖 LLM / 真实 agent 执行：直接构造 results + 临时 baseline 文件，验证
- save_baseline 只落可对比字段（id / routed_agents / routing_score / rubric_rate）
- compare_baseline 检测 exact 退化 / jaccard 退化 / rubric 退化 / 缺失题，并正确算漂移率
"""

from __future__ import annotations

import json

from agent_federation.eval.run_eval import compare_baseline, save_baseline


def _make_results() -> list[dict]:
    return [
        {
            "id": "q1",
            "routed_agents": ["行业动态搜索助手"],
            "routing_score": {"exact": True, "jaccard": 1.0},
            "rubric_score": {"hit": 3, "total": 3, "rate": 1.0},
        },
        {
            "id": "q2",
            "routed_agents": ["业务数据查询助手"],
            "routing_score": {"exact": True, "jaccard": 1.0},
        },
    ]


def test_save_baseline_strips_answer(tmp_path):
    results = _make_results()
    results[0]["answer"] = "很长的答案全文不应进基线"  # 噪声字段
    baseline = tmp_path / "base.jsonl"
    save_baseline(results, baseline)

    rows = [json.loads(line) for line in baseline.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert "answer" not in rows[0]
    assert rows[0]["id"] == "q1"
    assert rows[0]["routing_score"] == {"exact": True, "jaccard": 1.0}
    assert rows[0]["rubric_rate"] == 1.0
    assert "rubric_rate" not in rows[1]  # 无 rubric_score 的题不写 rubric_rate


def test_compare_detects_exact_regression(tmp_path):
    baseline = tmp_path / "base.jsonl"
    save_baseline(_make_results(), baseline)

    # q1 路由退化为非精确匹配
    drifted = _make_results()
    drifted[0]["routing_score"] = {"exact": False, "jaccard": 0.5}
    rate = compare_baseline(drifted, baseline)
    assert rate == 0.5  # 1/2 题漂移


def test_compare_detects_missing_and_rubric_regression(tmp_path):
    baseline = tmp_path / "base.jsonl"
    save_baseline(_make_results(), baseline)

    drifted = [
        {
            "id": "q1",
            "routed_agents": ["行业动态搜索助手"],
            "routing_score": {"exact": True, "jaccard": 1.0},
            "rubric_score": {"hit": 1, "total": 3, "rate": 0.33},  # rubric 退化
        },
        # q2 缺失
    ]
    rate = compare_baseline(drifted, baseline)
    assert rate == 1.0  # 2/2 漂移（rubric 退化 + 缺失）


def test_compare_clean_no_drift(tmp_path):
    baseline = tmp_path / "base.jsonl"
    save_baseline(_make_results(), baseline)
    rate = compare_baseline(_make_results(), baseline)
    assert rate == 0.0
