"""件 13 Data Readiness 补全测试。

覆盖：
  - 数据源台账可查（三类源 + 必备字段）
  - 缺源降级（NOT_CONNECTED → 答'该指标待接入' + 不生成 SQL，INV-10）
  - Readiness Gate 六门状态可查（含 evidence）
  - SYNTHETIC 指标永不 Production Ready（INV-3）
  - BLOCKED 指标 → Data 门 NOT_READY
"""

from __future__ import annotations

import pytest

from exhibition_agent.foundation.data_source_registry import (
    PENDING_ANSWER,
    ReadinessLevel,
    SourceType,
    get_readiness_level,
    get_registry_summary,
    get_source,
    is_pending,
    list_sources,
    pending_answer,
)
from exhibition_agent.foundation.metric_registry import (
    get_metric_status,
    get_readiness,
)
from exhibition_agent.foundation.production_readiness_gate import (
    GATE_NOT_READY,
    GATE_PASS,
    GATE_READY,
    NOT_APPROVED,
    get_gate_status_with_evidence,
    is_production_ready,
)

# === 数据源台账可查 ===


def test_registry_has_three_source_types():
    """台账包含三类数据源：domain_api(8) / knowledge(1) / metric(5)。"""
    by_type = get_registry_summary()["by_type"]
    assert by_type.get("domain_api", 0) == 8
    assert by_type.get("knowledge", 0) == 1
    assert by_type.get("metric", 0) == 5


def test_list_sources_returns_all_with_required_fields():
    """每个数据源有 source_id, name, type, readiness_level, last_checked。"""
    sources = list_sources()
    assert len(sources) == 14  # 8 domain_api + 1 knowledge + 5 metric
    for s in sources:
        assert "source_id" in s and s["source_id"]
        assert "name" in s
        assert "type" in s
        assert "readiness_level" in s
        assert "last_checked" in s


def test_list_sources_filter_by_type_metric():
    """按类型过滤数据源：metric → 5 个。"""
    metrics = list_sources("metric")
    assert len(metrics) == 5
    assert all(s["type"] == SourceType.METRIC for s in metrics)


def test_list_sources_filter_by_type_domain_api():
    """按类型过滤数据源：domain_api → 8 个。"""
    apis = list_sources("domain_api")
    assert len(apis) == 8
    assert all(s["type"] == SourceType.DOMAIN_API for s in apis)


def test_get_source_by_id_knowledge():
    """按 source_id 查 knowledge_service → NOT_CONNECTED。"""
    s = get_source("knowledge_service")
    assert s is not None
    assert s["readiness_level"] == ReadinessLevel.NOT_CONNECTED


def test_get_source_by_id_domain_api():
    """按 source_id 查 api_exhibition → CONNECTED。"""
    s = get_source("api_exhibition")
    assert s is not None
    assert s["readiness_level"] == ReadinessLevel.CONNECTED


def test_get_source_not_found():
    assert get_source("nonexistent_source") is None
    assert get_readiness_level("nonexistent_source") is None


def test_metric_source_readiness_from_registry():
    """metric 源 readiness_level 从 metric_registry.json 推导。"""
    s = get_source("metric_booth_sell_through_rate")
    assert s is not None
    assert s["readiness_level"] == ReadinessLevel.PARTIAL
    assert s["status"] == "BLOCKED"


def test_metric_source_connected():
    """exhibitor_count 指标 → CONNECTED。"""
    s = get_source("metric_exhibitor_count")
    assert s is not None
    assert s["readiness_level"] == ReadinessLevel.CONNECTED


# === 缺源降级（INV-10）===


def test_knowledge_source_is_pending():
    """knowledge-service NOT_CONNECTED → is_pending=True。"""
    assert is_pending("knowledge_service") is True


def test_pending_answer_no_sql_inv10():
    """NOT_CONNECTED → 答'该指标待接入' + 不生成 SQL（INV-10）。"""
    result = pending_answer("knowledge_service")
    assert result["degraded"] is True
    assert result["answer"] == PENDING_ANSWER
    assert result["answer"] == "该指标待接入"
    assert result["sql_generated"] is False  # INV-10：全程不生成 SQL


def test_connected_source_not_pending():
    """CONNECTED 源不触发降级。"""
    assert is_pending("api_exhibition") is False
    result = pending_answer("api_exhibition")
    assert result["degraded"] is False
    assert result["answer"] is None


def test_partial_metric_source_not_pending():
    """PARTIAL 源（BLOCKED 指标）不触发 NOT_CONNECTED 降级。"""
    assert is_pending("metric_booth_sell_through_rate") is False


def test_registry_summary_readiness_counts():
    """台账 readiness 分布：8 CONNECTED(api) + 3 CONNECTED(metric) + 2 PARTIAL(metric) + 1 NOT_CONNECTED(knowledge)。"""
    by_r = get_registry_summary()["by_readiness"]
    assert by_r.get("CONNECTED", 0) == 11  # 8 domain_api + 3 metric(exhibitor_count/booth_revenue/venue_utilization_rate)
    assert by_r.get("PARTIAL", 0) == 2  # booth_sell_through_rate + booth_vacancy_rate
    assert by_r.get("NOT_CONNECTED", 0) == 1  # knowledge_service


# === Readiness Gate 六门状态可查（含 evidence）===


def test_get_gate_status_with_evidence_returns_six_gates():
    """get_gate_status_with_evidence 返回六门 + evidence。"""
    result = get_gate_status_with_evidence()
    assert "gates" in result
    assert set(result["gates"].keys()) == {
        "identity",
        "knowledge",
        "data",
        "evaluation",
        "security",
        "observability",
    }
    for gid, g in result["gates"].items():
        assert g["status"] in (GATE_NOT_READY, GATE_READY, GATE_PASS)
        assert "reason" in g
        assert "details" in g


def test_gate_status_aggregation_not_approved():
    """当前六门未全 PASS → NOT_APPROVED。"""
    result = get_gate_status_with_evidence()
    assert result["conclusion"] == NOT_APPROVED
    assert result["approved"] is False
    assert len(result["failed_gates"]) > 0


def test_knowledge_gate_reads_knowledge_lifecycle():
    """Knowledge 门读 knowledge_lifecycle.knowledge_readiness() 状态。"""
    result = get_gate_status_with_evidence()
    kg = result["gates"]["knowledge"]
    assert kg["status"] == GATE_NOT_READY
    assert "语料未接入" in kg["reason"]


def test_security_gate_reads_data_egress():
    """Security 门读 data_egress.get_security_readiness() 状态。"""
    result = get_gate_status_with_evidence()
    sg = result["gates"]["security"]
    assert sg["status"] == GATE_NOT_READY
    assert "出域策略" in sg["reason"]


def test_evaluation_gate_reads_evaluation():
    """Evaluation 门读 evaluation.get_evaluation_readiness() 状态。"""
    result = get_gate_status_with_evidence()
    eg = result["gates"]["evaluation"]
    assert eg["status"] == GATE_NOT_READY
    assert "Golden Set" in eg["reason"]


def test_identity_gate_evidence():
    """Identity 门返回 F01 占位状态 + evidence。"""
    result = get_gate_status_with_evidence()
    ig = result["gates"]["identity"]
    assert ig["status"] == GATE_NOT_READY
    assert "F01" in ig["reason"]
    assert "signing" in ig["details"]


def test_observability_gate_evidence():
    """Observability 门返回占位状态 + evidence。"""
    result = get_gate_status_with_evidence()
    og = result["gates"]["observability"]
    assert og["status"] == GATE_NOT_READY
    assert "C4" in og["details"]["trace_fields"]


def test_data_gate_reads_metric_registry():
    """Data 门读 metric_registry + 执行 sql_template；有 BLOCKED 指标 → NOT_READY。"""
    result = get_gate_status_with_evidence()
    dg = result["gates"]["data"]
    assert dg["status"] == GATE_NOT_READY


# === SYNTHETIC 指标永不 Production Ready（INV-3）===


@pytest.mark.parametrize("skill_id", [
    "recommend_organizer",
    "recommend_venue",
    "recommend_exhibition",
    "get_strategy_insight",
    "get_forecast",
])
def test_synthetic_skill_never_production_ready(skill_id):
    """SYNTHETIC skill 永不 Production Ready（INV-3 硬规则）。"""
    readiness = get_readiness(skill_id)
    assert readiness == "SYNTHETIC", f"{skill_id} 应为 SYNTHETIC，实际 {readiness}"

    result = is_production_ready(skill_id)
    assert result["production_ready"] is False
    assert "SYNTHETIC" in result["reason"]
    assert result["label"] == "演示/非生产"


# === BLOCKED 指标 → NOT_READY ===


def test_blocked_metric_status():
    """booth_sell_through_rate / booth_vacancy_rate 是 BLOCKED。"""
    assert get_metric_status("booth_sell_through_rate") == "BLOCKED"
    assert get_metric_status("booth_vacancy_rate") == "BLOCKED"


def test_blocked_metric_in_data_gate_not_ready():
    """BLOCKED 指标 → Data 门 NOT_READY。"""
    result = get_gate_status_with_evidence()
    dg = result["gates"]["data"]
    assert dg["status"] == GATE_NOT_READY
    # details 中应能看到 BLOCKED 指标的判定
    details = dg["details"]
    blocked_metrics = [d for d in details if d.get("status") == "BLOCKED"]
    assert len(blocked_metrics) == 2


def test_blocked_metric_skill_not_production_ready():
    """依赖 BLOCKED 指标的 skill（get_venue_operation）不 Production Ready。"""
    result = is_production_ready("get_venue_operation")
    assert result["production_ready"] is False


def test_write_skill_not_production_ready():
    """写操作（create_lead）readiness=N/A (write)，不 Production Ready。"""
    result = is_production_ready("create_lead")
    assert result["production_ready"] is False
    assert result["label"] == "N/A (write)"
