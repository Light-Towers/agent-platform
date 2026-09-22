"""件 15 治理评测框架测试。

覆盖扩展后的 evaluation.py：
  - Golden Set 加载/保存（JSON / JSONL）
  - 四类评估器正确判定（mock 数据，不需真实语料）
  - Groundedness 强制（无 citation → 拒绝）
  - 跨租户负样本自动生成
  - Model Router 对接（model_cost 字段）
  - 审计记录写入

设计依据：foundation/evaluation.py 四类 golden + §18.8 Groundedness + §17.5 Model Router。
"""

from __future__ import annotations

import json

import pytest

from exhibition_agent.foundation import evaluation
from exhibition_agent.foundation.evaluation import (
    GoldenCase,
    GoldenCategory,
    assert_groundedness,
    assert_regression_before_deploy,
    generate_cross_tenant_negative_cases,
    get_evaluation_readiness,
    load_golden_cases,
    run_batch_evaluation,
    run_evaluation,
    save_golden_cases,
)


# ---------------------------------------------------------------------------
# 公共 fixture：隔离审计日志，不污染真实日志
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path, monkeypatch):
    audit_path = tmp_path / "test_eval_audit.json"
    monkeypatch.setattr(evaluation, "_AUDIT_LOG_PATH", str(audit_path))
    return audit_path


def _make_case(category, query="q", tenant_id="tenant_A", candidates=None, expected=None):
    return GoldenCase(
        category=category,
        query=query,
        tenant_context={"tenant_id": tenant_id},
        candidates=candidates or [],
        expected=expected or {},
    )


def _published_candidate(kid="k1", tenant_id="tenant_A", scope="PRIVATE"):
    return {
        "knowledge_id": kid,
        "tenant_id": tenant_id,
        "scope_type": scope,
        "status": "PUBLISHED",
        "authority": "展会主办方",
        "effective_from": "2020-01-01",
        "effective_to": "2099-12-31",
        "exhibition_id": "exp_001",
        "citation": {"knowledge_id": kid, "authority": "展会主办方"},
    }


# ---------------------------------------------------------------------------
# 1. Golden Set 加载/保存
# ---------------------------------------------------------------------------
class TestGoldenSetLoadSave:
    def test_load_json_array(self, tmp_path):
        data = [
            {
                "category": "positive",
                "query": "q1",
                "tenant_context": {"tenant_id": "A"},
                "candidates": [],
                "expected": {"min_hits": 1},
            }
        ]
        path = tmp_path / "golden.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cases = load_golden_cases(str(path))
        assert len(cases) == 1
        assert cases[0].category == GoldenCategory.POSITIVE
        assert cases[0].query == "q1"
        assert cases[0].tenant_context == {"tenant_id": "A"}

    def test_load_jsonl(self, tmp_path):
        lines = [
            json.dumps({"category": "positive", "query": "q1", "tenant_context": {}, "candidates": [], "expected": {}}, ensure_ascii=False),
            json.dumps({"category": "cross_tenant_negative", "query": "q2", "tenant_context": {}, "candidates": [], "expected": {}}, ensure_ascii=False),
        ]
        path = tmp_path / "golden.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")

        cases = load_golden_cases(str(path))
        assert len(cases) == 2
        assert cases[0].category == GoldenCategory.POSITIVE
        assert cases[1].category == GoldenCategory.CROSS_TENANT_NEGATIVE

    def test_load_jsonl_skips_blank_lines(self, tmp_path):
        path = tmp_path / "golden.jsonl"
        path.write_text(
            json.dumps({"category": "positive", "query": "q", "tenant_context": {}, "candidates": [], "expected": {}}) + "\n\n",
            encoding="utf-8",
        )
        cases = load_golden_cases(str(path))
        assert len(cases) == 1

    def test_load_single_object_json(self, tmp_path):
        """单个 JSON 对象（非数组）也能加载。"""
        path = tmp_path / "single.json"
        path.write_text(
            json.dumps({"category": "positive", "query": "q", "tenant_context": {}, "candidates": [], "expected": {}}),
            encoding="utf-8",
        )
        cases = load_golden_cases(str(path))
        assert len(cases) == 1

    def test_save_then_load_roundtrip(self, tmp_path):
        cases = [
            _make_case(GoldenCategory.POSITIVE, query="q1", candidates=[_published_candidate()]),
            _make_case(GoldenCategory.CONFLICT_SET, query="q2", expected={"has_conflict": True}),
        ]
        path = tmp_path / "out" / "golden.json"
        save_golden_cases(cases, str(path))

        loaded = load_golden_cases(str(path))
        assert len(loaded) == 2
        assert loaded[0].category == GoldenCategory.POSITIVE
        assert loaded[0].query == "q1"
        assert loaded[1].category == GoldenCategory.CONFLICT_SET
        assert loaded[1].expected == {"has_conflict": True}

    def test_save_creates_parent_dir(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "golden.json"
        save_golden_cases([], str(path))
        assert path.exists()

    def test_category_enum_serialized_as_string(self, tmp_path):
        cases = [_make_case(GoldenCategory.LIFECYCLE_NEGATIVE)]
        path = tmp_path / "g.json"
        save_golden_cases(cases, str(path))
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        assert raw[0]["category"] == "lifecycle_negative"


# ---------------------------------------------------------------------------
# 2. 四类评估器正确判定（mock 数据）
# ---------------------------------------------------------------------------
class TestEvaluators:
    def test_positive_pass_with_citation(self):
        case = _make_case(
            GoldenCategory.POSITIVE,
            candidates=[_published_candidate()],
            expected={"min_hits": 1},
        )
        report = run_evaluation([case])
        assert report["passed"] == 1
        assert report["results"][0]["passed"] is True

    def test_positive_fail_without_citation(self):
        cand = _published_candidate()
        del cand["citation"]
        del cand["knowledge_id"]
        case = _make_case(
            GoldenCategory.POSITIVE,
            candidates=[cand],
            expected={"min_hits": 1},
        )
        report = run_evaluation([case])
        assert report["failed"] == 1
        assert report["results"][0]["passed"] is False

    def test_cross_tenant_negative_pass_no_leak(self):
        """租户 B 查询，候选全是 B 自己的 → 越权召回=0。"""
        case = _make_case(
            GoldenCategory.CROSS_TENANT_NEGATIVE,
            tenant_id="tenant_B",
            candidates=[_published_candidate(kid="kB", tenant_id="tenant_B")],
        )
        report = run_evaluation([case])
        assert report["results"][0]["passed"] is True
        assert report["cross_tenant_violations"] == 0

    def test_cross_tenant_negative_fail_on_leak(self, monkeypatch):
        """scope filter 失效（检索层 bug）→ 跨租户候选泄漏 → 越权召回=1（P0）。

        当前 _mock_scope_filter 正确工作时跨租户 PRIVATE 候选会被过滤（violations=0）。
        此测试模拟检索层 bug（scope filter 退化为 identity），验证评估器能 catch 越权。
        """
        monkeypatch.setattr(evaluation, "_mock_scope_filter", lambda cands, tid: cands)
        case = _make_case(
            GoldenCategory.CROSS_TENANT_NEGATIVE,
            tenant_id="tenant_B",
            candidates=[_published_candidate(kid="kA", tenant_id="tenant_A")],
        )
        report = run_evaluation([case])
        assert report["results"][0]["passed"] is False
        assert report["cross_tenant_violations"] == 1

    def test_lifecycle_negative_pass_when_draft_filtered(self):
        """DRAFT 知识被 filter_published_for_retrieval 过滤 → 不进生产回答。"""
        cand = _published_candidate()
        cand["status"] = "DRAFT"
        case = _make_case(GoldenCategory.LIFECYCLE_NEGATIVE, candidates=[cand])
        report = run_evaluation([case])
        assert report["results"][0]["passed"] is True
        assert report["lifecycle_violations"] == 0

    def test_lifecycle_negative_detail_counts_non_published_input(self):
        cand = _published_candidate()
        cand["status"] = "EXPIRED"
        case = _make_case(GoldenCategory.LIFECYCLE_NEGATIVE, candidates=[cand])
        report = run_evaluation([case])
        assert report["results"][0]["passed"] is True
        assert report["results"][0]["non_published_in_input"] == 1

    def test_conflict_set_pass_with_warning(self):
        cand = _published_candidate()
        cand["conflict_warning"] = "垂类 vs 通用"
        case = _make_case(
            GoldenCategory.CONFLICT_SET,
            candidates=[cand],
            expected={"has_conflict": True},
        )
        report = run_evaluation([case])
        assert report["results"][0]["passed"] is True

    def test_conflict_set_pass_no_conflict_no_warning(self):
        case = _make_case(
            GoldenCategory.CONFLICT_SET,
            candidates=[_published_candidate()],
            expected={"has_conflict": False},
        )
        report = run_evaluation([case])
        assert report["results"][0]["passed"] is True

    def test_mixed_categories_aggregate(self):
        # positive 通过 + positive 无 citation 失败 → passed=1 failed=1
        cases = [
            _make_case(GoldenCategory.POSITIVE, candidates=[_published_candidate()], expected={"min_hits": 1}),
            _make_case(GoldenCategory.POSITIVE, candidates=[], expected={"min_hits": 1}),
        ]
        report = run_evaluation(cases)
        assert report["total"] == 2
        assert report["passed"] == 1
        assert report["failed"] == 1


# ---------------------------------------------------------------------------
# 3. Groundedness 强制（§18.8：无 citation → 拒绝）
# ---------------------------------------------------------------------------
class TestGroundedness:
    def test_knowledge_response_with_citation_passes(self):
        result = assert_groundedness("答案是...", [{"knowledge_id": "k1"}])
        assert result["ok"] is True
        assert result["answer"] == "答案是..."

    def test_knowledge_response_without_citation_rejected(self):
        result = assert_groundedness("答案是...", [])
        assert result["ok"] is False
        assert result["answer"] is None
        assert "§18.8" in result["reason"]

    def test_knowledge_response_none_citations_rejected(self):
        result = assert_groundedness("答案是...", None)
        assert result["ok"] is False
        assert result["answer"] is None

    def test_non_knowledge_response_passes_without_citation(self):
        """闲聊/操作确认不强制 citation。"""
        result = assert_groundedness("好的，已为您操作", [], is_knowledge_response=False)
        assert result["ok"] is True
        assert result["answer"] == "好的，已为您操作"

    def test_non_knowledge_response_with_citation_passes(self):
        result = assert_groundedness("好的", [{"k": "v"}], is_knowledge_response=False)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# 4. 跨租户负样本自动生成
# ---------------------------------------------------------------------------
class TestCrossTenantNegativeGeneration:
    def test_generates_negative_from_positive(self):
        positive = _make_case(
            GoldenCategory.POSITIVE,
            query="A的知识",
            tenant_id="tenant_A",
            candidates=[_published_candidate(tenant_id="tenant_A")],
        )
        negatives = generate_cross_tenant_negative_cases([positive])
        assert len(negatives) == 1
        neg = negatives[0]
        assert neg.category == GoldenCategory.CROSS_TENANT_NEGATIVE
        assert neg.tenant_context["tenant_id"] == "tenant_A_SPOOF"
        assert neg.tenant_context["spoofed_from"] == "tenant_A"
        assert neg.candidates == positive.candidates
        assert neg.expected["violation_count"] == 0

    def test_skips_non_positive_cases(self):
        conflict = _make_case(GoldenCategory.CONFLICT_SET)
        negatives = generate_cross_tenant_negative_cases([conflict])
        assert negatives == []

    def test_generated_negative_evaluates_as_violation(self, monkeypatch):
        """生成的负样本：scope filter 失效时，A_SPOOF 查询 A 的知识 → 检测到越权召回。

        scope filter 正确时 A 的候选会被过滤（无越权）；此测试模拟检索层 bug，
        验证生成的负样本能 catch 越权召回。
        """
        monkeypatch.setattr(evaluation, "_mock_scope_filter", lambda cands, tid: cands)
        positive = _make_case(
            GoldenCategory.POSITIVE,
            tenant_id="tenant_A",
            candidates=[_published_candidate(tenant_id="tenant_A")],
        )
        negatives = generate_cross_tenant_negative_cases([positive])
        report = run_evaluation(negatives)
        # 候选是 A 的 PRIVATE 知识，查询租户是 A_SPOOF → 越权召回
        assert report["cross_tenant_violations"] == 1
        assert report["results"][0]["passed"] is False

    def test_empty_input_returns_empty(self):
        assert generate_cross_tenant_negative_cases([]) == []

    def test_multiple_positives_generate_multiple_negatives(self):
        positives = [
            _make_case(GoldenCategory.POSITIVE, query=f"q{i}", tenant_id=f"t{i}")
            for i in range(3)
        ]
        negatives = generate_cross_tenant_negative_cases(positives)
        assert len(negatives) == 3
        assert {n.tenant_context["tenant_id"] for n in negatives} == {"t0_SPOOF", "t1_SPOOF", "t2_SPOOF"}


# ---------------------------------------------------------------------------
# 5. Model Router 对接（model_cost 字段）
# ---------------------------------------------------------------------------
class TestModelCostReport:
    def test_report_contains_model_cost(self):
        report = run_evaluation([_make_case(GoldenCategory.POSITIVE, candidates=[_published_candidate()], expected={"min_hits": 1})])
        assert "model_cost" in report
        mc = report["model_cost"]
        assert "total_cost" in mc
        assert "model_usage" in mc
        assert "status" in mc

    def test_model_cost_default_zero(self):
        report = run_evaluation([])
        assert report["model_cost"]["total_cost"] == 0.0

    def test_model_usage_has_all_categories(self):
        report = run_evaluation([])
        usage = report["model_cost"]["model_usage"]
        assert set(usage.keys()) == {"Small", "Private", "Cloud", "deny"}

    def test_model_cost_status_marks_pending(self):
        report = run_evaluation([])
        assert "待标定" in report["model_cost"]["status"]


# ---------------------------------------------------------------------------
# 6. 批量运行 + 审计记录写入
# ---------------------------------------------------------------------------
class TestBatchAndAudit:
    def test_run_batch_from_list(self):
        cases = [_make_case(GoldenCategory.POSITIVE, candidates=[_published_candidate()], expected={"min_hits": 1})]
        report = run_batch_evaluation(cases)
        assert report["total"] == 1
        assert report["passed"] == 1

    def test_run_batch_from_file(self, tmp_path):
        data = [{"category": "positive", "query": "q", "tenant_context": {"tenant_id": "A"},
                 "candidates": [], "expected": {"min_hits": 1}}]
        path = tmp_path / "golden.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        report = run_batch_evaluation(str(path))
        assert report["total"] == 1

    def test_audit_written_after_run(self, _isolate_audit_log):
        report = run_evaluation([_make_case(GoldenCategory.POSITIVE, candidates=[_published_candidate()], expected={"min_hits": 1})])
        assert _isolate_audit_log.exists()
        with open(_isolate_audit_log, "r", encoding="utf-8") as f:
            logs = json.load(f)
        assert len(logs) == 1
        assert logs[0]["timestamp"] == report["timestamp"]

    def test_audit_appends_multiple_runs(self, _isolate_audit_log):
        for _ in range(3):
            run_evaluation([])
        with open(_isolate_audit_log, "r", encoding="utf-8") as f:
            logs = json.load(f)
        assert len(logs) == 3

    def test_regression_gate_blocks_on_failure(self):
        case = _make_case(GoldenCategory.POSITIVE, candidates=[], expected={"min_hits": 1})
        report = run_evaluation([case])
        gate = assert_regression_before_deploy(report)
        assert gate["can_deploy"] is False

    def test_regression_gate_passes_on_success(self):
        case = _make_case(GoldenCategory.POSITIVE, candidates=[_published_candidate()], expected={"min_hits": 1})
        report = run_evaluation([case])
        gate = assert_regression_before_deploy(report)
        assert gate["can_deploy"] is True


# ---------------------------------------------------------------------------
# 7. readiness 查询（不破坏现有接口）
# ---------------------------------------------------------------------------
class TestReadiness:
    def test_readiness_returns_not_ready(self):
        r = get_evaluation_readiness()
        assert r["status"] == "NOT_READY"
        assert "details" in r
