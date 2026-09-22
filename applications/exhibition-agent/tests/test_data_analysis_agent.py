"""data_analysis.query skill 测试（P1 骨架）。

覆盖：
- skill 定义完整
- Metric Registry 校验（VERIFIED 可查 / BLOCKED / NOT_CONNECTED / CONNECTED 非 VERIFIED）
- INV-10 回归（非 VERIFIED 不生成 SQL，经 supervisor 全链路）
- skill 挂到 Supervisor 图（注册表 + 图节点集合不变 + 路由分派）
"""

from __future__ import annotations

import pytest

from exhibition_agent.contract.envelope import Readiness
from exhibition_agent.contract.error_codes import PENDING_ANSWER
from exhibition_agent.foundation import metric_registry
from exhibition_agent.graph import nodes
from exhibition_agent.graph.supervisor import build_graph, run_supervisor
from exhibition_agent.observability.trace import InMemoryTraceRecorder
from exhibition_agent.skills.base_skill import BaseSkill, SkillContext
from exhibition_agent.skills.data_analysis.skill import DataAnalysisQuerySkill
from exhibition_agent.testing_helpers import ctx, ctx_header

# --- skill 定义完整 ---


def test_skill_definition_complete():
    """skill 定义完整：继承 BaseSkill、name/description 非空、只读。"""
    skill = DataAnalysisQuerySkill()
    assert isinstance(skill, BaseSkill)
    assert skill.name == "data_analysis.query"
    assert skill.description
    assert "nl2sql" in skill.description.lower() or "问数" in skill.description


# --- Metric Registry 校验 ---


@pytest.fixture
def skill_context(warehouse_client):
    context = ctx()
    return SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=warehouse_client,
        context_mode="jwt",
    )


async def test_metric_verified_returns_result(skill_context, monkeypatch):
    """VERIFIED → 非 pending 结果（骨架 stub，readiness=READY，不答'待接入'）。

    registry 当前无 VERIFIED 指标（待 F06 评测门禁升级），用 monkeypatch 模拟。
    """
    monkeypatch.setattr(metric_registry, "get_metric_status", lambda mid: "VERIFIED")
    skill = DataAnalysisQuerySkill()
    result = await skill.run(
        {"metric_id": "exhibitor_count", "nl_query": "参展商数量"},
        skill_context,
    )
    assert result.readiness == Readiness.READY
    assert result.answer != PENDING_ANSWER
    assert result.error_code is None
    assert result.data.get("skeleton") is True
    assert result.data.get("nl2sql_endpoint", "").startswith("TODO")


async def test_metric_blocked_answers_pending(skill_context):
    """BLOCKED → 答'待接入' + METRIC_BLOCKED + 不生成 SQL（INV-10）。"""
    skill = DataAnalysisQuerySkill()
    result = await skill.run(
        {"metric_id": "booth_sell_through_rate", "nl_query": "展位销售率"},
        skill_context,
    )
    assert result.answer == PENDING_ANSWER
    assert result.error_code == "METRIC_BLOCKED"
    assert result.readiness == Readiness.NOT_CONNECTED


async def test_metric_not_connected_answers_pending(skill_context):
    """metric 未登记（status=None）→ 答'待接入' + DATA_NOT_CONNECTED + 不生成 SQL。"""
    skill = DataAnalysisQuerySkill()
    result = await skill.run(
        {"metric_id": "nonexistent_metric_xyz", "nl_query": "某指标"},
        skill_context,
    )
    assert result.answer == PENDING_ANSWER
    assert result.error_code == "DATA_NOT_CONNECTED"
    assert result.readiness == Readiness.NOT_CONNECTED


async def test_metric_connected_but_not_verified_answers_pending(skill_context):
    """CONNECTED（非 VERIFIED）→ 答'待接入' + METRIC_NOT_VERIFIED（INV-10：非 VERIFIED 不得执行）。"""
    skill = DataAnalysisQuerySkill()
    result = await skill.run(
        {"metric_id": "exhibitor_count", "nl_query": "参展商数量"},
        skill_context,
    )
    assert result.answer == PENDING_ANSWER
    assert result.error_code == "METRIC_NOT_VERIFIED"
    assert result.readiness == Readiness.NOT_CONNECTED


async def test_missing_metric_id_answers_pending(skill_context):
    """缺 metric_id → 不校验、不执行（防绕过 Metric Registry）。"""
    skill = DataAnalysisQuerySkill()
    result = await skill.run({"nl_query": "某指标"}, skill_context)
    assert result.readiness == Readiness.NOT_CONNECTED
    assert result.error_code == "METRIC_NOT_VERIFIED"


# --- INV-10 回归（supervisor 全链路）---


@pytest.mark.parametrize("metric_id,expected_code", [
    ("booth_sell_through_rate", "METRIC_BLOCKED"),
    ("nonexistent_metric_xyz", "DATA_NOT_CONNECTED"),
    ("exhibitor_count", "METRIC_NOT_VERIFIED"),
])
async def test_inv10_non_verified_no_sql_via_supervisor(
    warehouse_client, metric_id, expected_code
):
    """非 VERIFIED → 经 supervisor 全链路答'待接入' + 全程零 SQL（INV-10）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "数据分析问数",
        "params": {
            "skill": "data_analysis.query",
            "metric_id": metric_id,
            "nl_query": "某指标",
        },
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
    })
    assert state["answer"] == PENDING_ANSWER, (
        f"INV-10 违反：{expected_code} 时必须答'{PENDING_ANSWER}'，实际答'{state['answer']}'"
    )
    assert state["sql_statements"] == [], (
        f"INV-10 违反：{expected_code} 时不得生成任何 SQL，实际 sql_statements={state['sql_statements']}"
    )
    result = state["skill_result"]
    assert result is not None
    assert result.error_code == expected_code


# --- skill 挂到 Supervisor 图 ---


def test_skill_registered_in_supervisor():
    """data_analysis.query 已注册到 Supervisor skill 注册表。"""
    assert "data_analysis.query" in nodes._SKILLS
    assert isinstance(nodes._SKILLS["data_analysis.query"], DataAnalysisQuerySkill)
    assert "venue.schedule.query" in nodes._SKILLS


def test_graph_node_set_unchanged_inv10_guard():
    """图节点集合保持 INV-10 结构守卫不变（data_analysis 经 run_skill 内分派，不新增节点）。"""
    compiled = build_graph()
    assert set(compiled.get_graph().nodes) == {
        "__start__",
        "__end__",
        "select_skill",
        "run_skill",
        "emit_trace",
    }, (
        "INV-10 结构守卫：data_analysis skill 须经 run_skill 内分派，不得新增 LangGraph 节点"
    )


async def test_supervisor_routes_to_data_analysis_by_explicit_skill(warehouse_client, monkeypatch):
    """params.skill=data_analysis.query → 路由到 data_analysis（VERIFIED 骨架路径）。"""
    monkeypatch.setattr(metric_registry, "get_metric_status", lambda mid: "VERIFIED")
    context = ctx()
    state = await run_supervisor({
        "query": "数据分析问数",
        "params": {
            "skill": "data_analysis.query",
            "metric_id": "exhibitor_count",
            "nl_query": "参展商数量",
        },
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
    })
    result = state["skill_result"]
    assert result is not None
    assert result.readiness == Readiness.READY
    assert state["sql_statements"] == []


async def test_supervisor_routes_to_data_analysis_by_nl_query(warehouse_client):
    """params.nl_query 存在（无显式 skill）→ 路由到 data_analysis（BLOCKED → 待接入）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "数据分析问数",
        "params": {
            "metric_id": "booth_sell_through_rate",
            "nl_query": "展位销售率",
        },
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
    })
    result = state["skill_result"]
    assert result is not None
    assert result.error_code == "METRIC_BLOCKED"
    assert state["answer"] == PENDING_ANSWER


async def test_supervisor_default_route_unchanged_for_venue(warehouse_client):
    """无 skill/nl_query 参数 → 默认 venue.schedule.query（现有测试路由不受影响）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "查询档期",
        "params": {"exhibition_id": "ex-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    })
    assert state.get("skill_name") == "venue.schedule.query"
