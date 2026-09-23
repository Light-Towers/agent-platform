"""
F05 Evaluation & Golden Set — 脚手架版

四类 golden：
  Positive              — 租户 A query → A 的知识 / 公开知识（命中正确 scope + citation）
  Cross-Tenant Negative — Tenant A query 不得召回 B 的知识（越权召回=0）
  Lifecycle Negative    — DRAFT/REVIEWING/EXPIRED/SUPERSEDED/REVOKED 不得进生产回答
  Conflict Set          — 垂类 vs 通用、HARD vs SOFT、业务事实 vs 文档知识（带 Conflict Warning）

硬规则：
  越权召回 = 0、过期知识召回 = 0，每次检索必检
  统计类判据无基线标"待标定"，禁止拿无基线数字自证
  无 Citation 的知识型答案 → 拒绝作答

依赖：
  F03 knowledge_lifecycle.filter_published_for_retrieval（已落地 ✅）
  F01 execution_context.enforce_scope_filter（尚未落地 → MVP 内联 mock，标注 TODO）

迁移来源：mingyang-warehouse/ontology/web/backend/evaluation.py（2026-09-22）
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ._audit_writer import append_audit_record
from .knowledge_lifecycle import KNOWLEDGE_STATUS, filter_published_for_retrieval

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_AUDIT_LOG_PATH = os.path.join(_DATA_DIR, "evaluation_audit.json")


class GoldenCategory(str, Enum):
    POSITIVE = "positive"
    CROSS_TENANT_NEGATIVE = "cross_tenant_negative"
    LIFECYCLE_NEGATIVE = "lifecycle_negative"
    CONFLICT_SET = "conflict_set"


@dataclass
class GoldenCase:
    category: GoldenCategory
    query: str
    tenant_context: dict
    candidates: list
    expected: dict


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_scope_filter(candidates: list, tenant_id: str) -> list:
    """
    MVP 内联 mock scope 过滤：仅保留 tenant_id 匹配或 scope_type=PUBLIC 的候选。
    TODO: F01 execution_context.enforce_scope_filter 落地后替换此函数。
    """
    result = []
    for c in candidates:
        item_tenant = c.get("tenant_id", "")
        item_scope = c.get("scope_type", "PRIVATE")
        if item_scope == "PUBLIC" or item_tenant == tenant_id:
            result.append(c)
    return result


def _has_citation(candidate: dict) -> bool:
    """检查候选是否带 citation（knowledge_id / authority / version / effective_date）。"""
    return bool(candidate.get("citation") or candidate.get("knowledge_id"))


def _is_non_published(candidate: dict) -> bool:
    """检查候选是否为非 PUBLISHED 状态。"""
    status = candidate.get("status", "")
    return status in (
        KNOWLEDGE_STATUS.DRAFT,
        KNOWLEDGE_STATUS.REVIEWING,
        KNOWLEDGE_STATUS.EXPIRED,
        KNOWLEDGE_STATUS.SUPERSEDED,
        KNOWLEDGE_STATUS.REVOKED,
    )


def _evaluate_positive(case: GoldenCase) -> dict:
    """Positive：命中正确 scope + 带 citation。"""
    tenant_id = case.tenant_context.get("tenant_id", "")
    scoped = _mock_scope_filter(case.candidates, tenant_id)
    expected_count = case.expected.get("min_hits", 1)

    hits_with_citation = [c for c in scoped if _has_citation(c)]
    cross_tenant_leak = [
        c for c in scoped
        if c.get("tenant_id", "") != tenant_id and c.get("scope_type") != "PUBLIC"
    ]

    passed = len(hits_with_citation) >= expected_count and len(cross_tenant_leak) == 0

    return {
        "passed": passed,
        "scoped_count": len(scoped),
        "hits_with_citation": len(hits_with_citation),
        "cross_tenant_leak": len(cross_tenant_leak),
        "detail": "命中正确 scope 且带 citation" if passed else "未命中或缺少 citation",
    }


def _evaluate_cross_tenant_negative(case: GoldenCase) -> dict:
    """Cross-Tenant Negative：越权召回数 = 0。"""
    tenant_id = case.tenant_context.get("tenant_id", "")
    scoped = _mock_scope_filter(case.candidates, tenant_id)

    violations = [
        c for c in scoped
        if c.get("tenant_id", "") != tenant_id and c.get("scope_type") != "PUBLIC"
    ]

    return {
        "passed": len(violations) == 0,
        "violation_count": len(violations),
        "detail": "越权召回=0" if len(violations) == 0 else f"越权召回={len(violations)}（P0）",
    }


def _evaluate_lifecycle_negative(case: GoldenCase) -> dict:
    """Lifecycle Negative：非 PUBLISHED 不得进生产回答。"""
    filtered = filter_published_for_retrieval(case.candidates)
    non_published_in_result = [c for c in filtered if _is_non_published(c)]
    non_published_in_input = [c for c in case.candidates if _is_non_published(c)]

    return {
        "passed": len(non_published_in_result) == 0,
        "non_published_in_input": len(non_published_in_input),
        "non_published_in_result": len(non_published_in_result),
        "filtered_count": len(filtered),
        "detail": "过期/非发布态知识未进入生产回答" if len(non_published_in_result) == 0
                  else f"非发布态知识泄漏={len(non_published_in_result)}（P0）",
    }


def _evaluate_conflict_set(case: GoldenCase) -> dict:
    """
    Conflict Set：标记 conflict_warning。
    ⚠ 不含"同具体性、不同租户"样本（F03 D5 判定规则未定，留 TODO）。
    """
    has_conflict = case.expected.get("has_conflict", True)
    candidates_with_warning = [
        c for c in case.candidates if c.get("conflict_warning")
    ]

    passed = has_conflict == (len(candidates_with_warning) > 0)

    return {
        "passed": passed,
        "conflict_warning_count": len(candidates_with_warning),
        "expected_conflict": has_conflict,
        "detail": "冲突标记正确" if passed else "冲突标记与预期不符",
        "todo": "F03 D5: 同具体性不同租户冲突判定规则未定，此类样本不含",
    }


_EVALUATORS = {
    GoldenCategory.POSITIVE: _evaluate_positive,
    GoldenCategory.CROSS_TENANT_NEGATIVE: _evaluate_cross_tenant_negative,
    GoldenCategory.LIFECYCLE_NEGATIVE: _evaluate_lifecycle_negative,
    GoldenCategory.CONFLICT_SET: _evaluate_conflict_set,
}


def run_evaluation(cases: list) -> dict:
    """
    对每用例跑过滤 + 判定，返回汇总报告。
    统计类指标标"待标定"，不输出无基线数字自证。
    """
    results = []
    for case in cases:
        evaluator = _EVALUATORS.get(case.category)
        if evaluator is None:
            result = {"passed": False, "detail": f"未知类别: {case.category}"}
        else:
            result = evaluator(case)
        results.append({
            "category": str(case.category),
            "query": case.query,
            "tenant_id": case.tenant_context.get("tenant_id", ""),
            **result,
        })

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed

    cross_tenant_violations = sum(
        r.get("violation_count", 0) for r in results
        if r["category"] == str(GoldenCategory.CROSS_TENANT_NEGATIVE)
    )
    lifecycle_violations = sum(
        r.get("non_published_in_result", 0) for r in results
        if r["category"] == str(GoldenCategory.LIFECYCLE_NEGATIVE)
    )
    no_citation_count = sum(
        1 for r in results
        if r["category"] == str(GoldenCategory.POSITIVE) and not r.get("passed")
    )

    report = {
        "timestamp": _now_iso(),
        "total": total,
        "passed": passed,
        "failed": failed,
        "cross_tenant_violations": cross_tenant_violations,
        "lifecycle_violations": lifecycle_violations,
        "no_citation_failures": no_citation_count,
        "recall_at_k": "待标定（D3 基线未定，禁止无基线数字自证）",
        "conflict_accuracy": "待标定（D3 基线未定）",
        "model_cost": _build_model_cost_report(results),
        "results": results,
    }

    _write_audit(report)
    return report


def _write_audit(report: dict):
    """写审计日志。"""
    append_audit_record(_AUDIT_LOG_PATH, report)


def assert_regression_before_deploy(report: dict) -> dict:
    """
    模型/Prompt 变更未回归即上线次数 = 0。
    框架强制：部署前必须跑 run_evaluation 并检查此函数。
    """
    if report.get("failed", 0) > 0:
        return {
            "can_deploy": False,
            "reason": f"回归未通过：{report['failed']} 例失败",
            "violations": {
                "cross_tenant": report.get("cross_tenant_violations", 0),
                "lifecycle": report.get("lifecycle_violations", 0),
                "no_citation": report.get("no_citation_failures", 0),
            },
        }
    return {"can_deploy": True, "reason": "回归全通过"}


def get_evaluation_readiness() -> dict:
    """
    供 F06 evaluation 门占位查询。
    不要改 readiness_gate_manifest.json 的 implemented 字段。
    """
    return {
        "status": "NOT_READY",
        "reason": "Golden Set 待 D1 责任人确认 + D3 基线标定 + 真实检索层未接入",
        "details": {
            "D1_golden_set_owner": "待业务方拍板（知识运营+业务共建，超管终审）",
            "D2_expansion_cadence": "语料到位后",
            "D3_baseline": "统计指标待标定",
            "F01_dependency": "scope 过滤用 mock，待 F01 落地后切换",
            "F03_dependency": "filter_published_for_retrieval 已复用 ✅",
            "retrieval_layer": "未接入（MVP 仅 mock 候选）",
        },
    }


# ---------------------------------------------------------------------------
# Golden Set 加载/保存（JSON / JSONL，格式与 GoldenCase dataclass 对齐）
# ---------------------------------------------------------------------------

def _dict_to_golden_case(d: dict) -> GoldenCase:
    """dict → GoldenCase（category 字符串转枚举）。"""
    category = d.get("category")
    if isinstance(category, str):
        category = GoldenCategory(category)
    return GoldenCase(
        category=category,
        query=d.get("query", ""),
        tenant_context=d.get("tenant_context", {}),
        candidates=d.get("candidates", []),
        expected=d.get("expected", {}),
    )


def _golden_case_to_dict(case: GoldenCase) -> dict:
    """GoldenCase → dict（category 枚举转字符串）。"""
    cat = case.category
    return {
        "category": cat.value if isinstance(cat, GoldenCategory) else str(cat),
        "query": case.query,
        "tenant_context": case.tenant_context,
        "candidates": case.candidates,
        "expected": case.expected,
    }


def load_golden_cases(path: str) -> list:
    """
    从文件加载 GoldenCase 列表。
    支持两种格式：
      - .jsonl：每行一个 JSON 对象（JSONL）
      - .json / 其他：JSON 数组（或单个对象）
    格式与 GoldenCase dataclass 对齐：category/query/tenant_context/candidates/expected。
    """
    cases = []
    if path.endswith(".jsonl"):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                cases.append(_dict_to_golden_case(json.loads(line)))
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = [data]
        for item in data:
            cases.append(_dict_to_golden_case(item))
    return cases


def save_golden_cases(cases: list, path: str) -> None:
    """保存 GoldenCase 列表到 JSON 文件（数组格式）。"""
    data = [_golden_case_to_dict(c) for c in cases]
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_batch_evaluation(source) -> dict:
    """
    批量运行评测。
    source 可为：
      - str / os.PathLike：golden cases 文件路径（JSON/JSONL），加载后跑 run_evaluation
      - list：GoldenCase 列表，直接跑 run_evaluation
    返回 run_evaluation 报告（含 model_cost 字段）。
    """
    if isinstance(source, (str, os.PathLike)):
        cases = load_golden_cases(str(source))
    else:
        cases = source
    return run_evaluation(cases)


# ---------------------------------------------------------------------------
# Groundedness 强制（§18.8：无 Citation 即无回答）
# ---------------------------------------------------------------------------

def assert_groundedness(
    answer: str,
    citations: list,
    is_knowledge_response: bool = True,
) -> dict:
    """
    §18.8 Groundedness 强制：无 Citation 即无回答。
    知识型响应（is_knowledge_response=True）citations 必填，缺失即拒绝作答。
    非知识型响应（闲聊 / 操作确认 / 元信息）不强制 citation。

    返回 {ok, answer, reason}：
      - ok=True, answer=原答案  → 可放行
      - ok=False, answer=None   → 拒绝作答（调用方不得返回原答案）
    """
    if not is_knowledge_response:
        return {"ok": True, "answer": answer, "reason": "非知识型响应，不强制 citation"}
    if not citations:
        return {
            "ok": False,
            "answer": None,
            "reason": "知识型响应无 citation → 拒绝作答（§18.8 Groundedness）",
        }
    return {"ok": True, "answer": answer, "reason": "citation 齐全"}


# ---------------------------------------------------------------------------
# 跨租户负样本自动生成（从 positive cases 派生，检测越权召回）
# ---------------------------------------------------------------------------

def generate_cross_tenant_negative_cases(positive_cases: list) -> list:
    """
    从 positive cases 自动生成跨租户负样本：
      原租户 A 的知识候选不变，把 tenant_context.tenant_id 换成伪造租户 B，
      期望 B 查询不得召回 A 的知识（越权召回=0）。

    仅处理 category==POSITIVE 的用例；其余原样跳过。
    生成的负样本 category=CROSS_TENANT_NEGATIVE，expected.violation_count=0。
    """
    negatives = []
    for case in positive_cases:
        if case.category != GoldenCategory.POSITIVE:
            continue
        original_tenant = case.tenant_context.get("tenant_id", "")
        spoofed_tenant = f"{original_tenant}_SPOOF" if original_tenant else "SPOOF_TENANT"

        new_tenant_context = dict(case.tenant_context)
        new_tenant_context["tenant_id"] = spoofed_tenant
        new_tenant_context["spoofed_from"] = original_tenant

        expected = {
            "violation_count": 0,
            "generated_from": "positive",
            "original_tenant": original_tenant,
        }

        negatives.append(GoldenCase(
            category=GoldenCategory.CROSS_TENANT_NEGATIVE,
            query=case.query,
            tenant_context=new_tenant_context,
            candidates=case.candidates,
            expected=expected,
        ))
    return negatives


# ---------------------------------------------------------------------------
# Model Router 对接：报告内 model/cost 字段
# ---------------------------------------------------------------------------

def _build_model_cost_report(results: list) -> dict:
    """
    构建 model/cost 汇总（对接 §17.5 Model Router）。
    当前未接入真实 LLM 调用，cost=0.0 占位，标"待标定"。
    真实接入后由调用方按 ModelDecision.cost 累加。
    """
    return {
        "total_cost": 0.0,
        "model_usage": {"Small": 0, "Private": 0, "Cloud": 0, "deny": 0},
        "status": "待标定（未接入真实 LLM 调用，cost=0.0 占位；接入后按 ModelDecision.cost 累加）",
    }
