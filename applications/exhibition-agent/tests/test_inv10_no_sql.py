"""INV-10 回归测试（本任务最重要的一条）。

METRIC_NOT_VERIFIED / METRIC_BLOCKED / DATA_NOT_CONNECTED → 回答"该指标待接入"，
且断言：全程未生成任何 SQL（INV-10：指标口径不可绕过，禁止 L3 text2sql 自算）。
"""

from __future__ import annotations

import pytest

from exhibition_agent.contract.envelope import Readiness
from exhibition_agent.contract.error_codes import PENDING_ANSWER
from exhibition_agent.graph.supervisor import build_graph, run_supervisor
from exhibition_agent.observability.trace import InMemoryTraceRecorder
from exhibition_agent.testing_helpers import ctx, ctx_header


def test_inv10_graph_structure_guards_no_sql_node():
    """结构守卫（审核 N4）：图节点集合固定为 select_skill → run_skill → emit_trace。

    原运行时断言 ``sql_statements == []`` 恒真（全仓无任何位置向 sql_statements append），
    不具备回归捕获能力；改为直接锁定图结构——若未来引入 L3 text2sql 类节点，
    本断言立即失败，INV-10「零 SQL」契约不再靠侥幸成立。
    """
    compiled = build_graph()
    assert set(compiled.get_graph().nodes) == {
        "__start__",
        "__end__",
        "select_skill",
        "run_skill",
        "emit_trace",
    }, (
        "INV-10 违规：Supervisor 图节点集合发生变化，疑似引入 L3 text2sql 节点；"
        "契约 §5 零 SQL 约束要求图内不得出现 SQL 生成节点"
    )


@pytest.mark.parametrize("scenario,expected_code", [
    ("metric_not_verified", "METRIC_NOT_VERIFIED"),
    ("metric_blocked", "METRIC_BLOCKED"),
    ("data_not_connected", "DATA_NOT_CONNECTED"),
])
async def test_inv10_metric_pending_answers_pending_and_no_sql(
    warehouse_client, scenario, expected_code
):
    """命中未 VERIFIED / BLOCKED / DATA_NOT_CONNECTED → 答'该指标待接入' + 全程零 SQL。"""
    context = ctx()
    recorder = InMemoryTraceRecorder()

    state = await run_supervisor({
        "query": "查询展位销售率",
        "params": {"exhibition_id": "ex-001", "metric": "sales_rate"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": recorder,
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": scenario},
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
    assert result.readiness == Readiness.NOT_CONNECTED

    trace = recorder.find_by_request_id(context.request_id)
    assert trace is not None
    assert trace.error_code == expected_code
    assert trace.model != "cloud", "INV-10 / F02：出域不得降级到云模型"


async def test_inv10_no_l3_text2sql_triggered(warehouse_client):
    """METRIC_BLOCKED 时 L3 text2sql 节点未被触发（sql_statements 恒空）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆空置率",
        "params": {"venue_id": "vn-001", "metric": "venue_occupancy"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "metric_blocked"},
    })

    assert state["answer"] == PENDING_ANSWER
    assert state["sql_statements"] == []
    assert "skill_result" in state
    assert state["skill_result"].error_code == "METRIC_BLOCKED"
