"""P1 Skill Router 接线测试（docs/TODO §3）：run_skill → route() 门禁链。

证明三件事：
  (a) venue.schedule.query 经 run_skill 执行前确实过了 route()（spy 断言）；
  (b) scope 不符（INV-4）→ route() 整体拒绝，skill 不执行、WarehouseClient 不被触达；
  (c) 生产模式 SYNTHETIC（F06 readiness）→ route() 拦截，skill 不执行、WarehouseClient 不被触达。

门禁只针对命中 nodes._CATALOG_ROUTE 的 skill；data_analysis.query 不直连 WarehouseClient，
不在映射表内（另测其跳过 route 仍正常执行）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from exhibition_agent.contract.envelope import Readiness
from exhibition_agent.foundation import metric_registry
from exhibition_agent.foundation.skill_router import route
from exhibition_agent.graph import nodes
from exhibition_agent.graph.nodes import run_skill
from exhibition_agent.testing_helpers import ctx, ctx_header


@pytest.fixture
def mock_nl2sql_success(monkeypatch):
    """Mock nl2sql-service HTTP 调用返回成功响应（与 test_data_analysis_agent 同形）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": "参展商数量为 42",
                "sql": "SELECT COUNT(*) FROM exhibitor",
                "error": None,
                "latency_ms": 10.0,
                "fallback": False,
            },
        )

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)



def _state(
    *,
    ec,
    warehouse_client,
    params: dict[str, Any],
    skill_name: str = "venue.schedule.query",
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造 run_skill 所需的最小 state。"""
    return {
        "skill_name": skill_name,
        "params": params,
        "execution_context": ec,
        "execution_context_header": ctx_header(ec),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "extra_headers": extra_headers or {},
        "sql_statements": [],
    }


def _blocking_warehouse() -> AsyncMock:
    """warehouse_client 替身：get_rest 一旦被调用即失败（证明门禁在执行前已阻断）。"""
    client = AsyncMock()
    client.get_rest = AsyncMock(
        side_effect=AssertionError("门禁应已阻断，WarehouseClient.get_rest 不得被调用")
    )
    return client


def _spy_route(monkeypatch) -> list[tuple[str, Any, dict[str, Any]]]:
    """把 nodes.route 换成记录调用的 spy（仍委托真实 route，保留门禁语义）。"""
    calls: list[tuple[str, Any, dict[str, Any]]] = []
    real_route = nodes.route

    def spy(skill_name: str, ctx=None, **discriminator) -> dict:
        calls.append((skill_name, ctx, discriminator))
        return real_route(skill_name, ctx, **discriminator)

    monkeypatch.setattr(nodes, "route", spy)
    return calls


def _patch_skill_run_guard(monkeypatch) -> dict[str, bool]:
    """把 venue skill 实例的 run 换成守卫：一旦被调用即记录并失败。"""
    flag = {"called": False}

    async def guard(params, ctx):  # noqa: ANN001 - 测试替身，签名对齐 BaseSkill.run
        flag["called"] = True
        raise AssertionError("门禁应已阻断，skill.run 不得被调用")

    monkeypatch.setattr(nodes._VENUE_SKILL, "run", guard)
    return flag


# (a) 接线证明：venue.schedule.query 经 run_skill 确实过 route()，且放行后正常执行。
async def test_run_skill_consults_route_and_allows_in_scope(warehouse_client, monkeypatch):
    calls = _spy_route(monkeypatch)
    ec = ctx(scopes=["exhibition:ex-001", "venue:vn-001"])
    state = _state(
        ec=ec,
        warehouse_client=warehouse_client,
        params={"venue_id": "vn-001"},
        extra_headers={"X-Mock-Scenario": "normal_200"},
    )

    out = await run_skill(state)

    # route() 被调用，且映射到 catalog skill get_venue_operation（card=schedule）。
    assert len(calls) == 1
    catalog_skill, passed_ctx, discriminator = calls[0]
    assert catalog_skill == "get_venue_operation"
    assert discriminator.get("card") == "schedule"
    assert discriminator.get("venue_id") == "vn-001"
    # 门禁拿到的是带 .scopes 的 ExecutionContext（scope 校验依赖它）。
    assert passed_ctx is ec

    # 放行 → skill 正常执行 → happy path 形状/结果保持不变。
    result = out["skill_result"]
    assert result is not None
    assert result.readiness == Readiness.READY
    assert out["error"] is None


# (b) scope 违规：route() 整体拒绝，skill 不执行、warehouse 不被触达，错误如实上浮。
async def test_run_skill_scope_violation_blocks_before_execution(monkeypatch):
    _spy_route(monkeypatch)
    run_guard = _patch_skill_run_guard(monkeypatch)
    warehouse = _blocking_warehouse()
    # 调用方 scope 只有 vn-001，却请求 vn-999 → INV-4 scope 不符。
    ec = ctx(scopes=["venue:vn-001"])
    state = _state(ec=ec, warehouse_client=warehouse, params={"venue_id": "vn-999"})

    out = await run_skill(state)

    assert run_guard["called"] is False
    warehouse.get_rest.assert_not_called()
    assert out["error"] == "SCOPE_DENIED"
    assert out["skill_result"].error_code == "SCOPE_DENIED"
    # 上浮的是 router 的 reason 原文（不是静默执行、不是泛化错误）。
    assert "scope 不符" in out["answer"]
    assert out["skill_result"].data["route_denied"] is True


# (c) readiness 拦截：生产模式 SYNTHETIC → route() 拒绝，skill 不执行、warehouse 不被触达。
async def test_run_skill_readiness_blocks_in_production(monkeypatch):
    _spy_route(monkeypatch)
    run_guard = _patch_skill_run_guard(monkeypatch)
    warehouse = _blocking_warehouse()
    monkeypatch.setenv("AGENT_MODE", "PRODUCTION")
    ec = ctx(scopes=["venue:vn-001"])
    # card=project_fit → catalog 解析到 venue_cf_recommend（readiness=SYNTHETIC）。
    state = _state(ec=ec, warehouse_client=warehouse, params={"card": "project_fit"})

    # 先证明真实 route() 在生产模式确实给出 SYNTHETIC readiness 拒绝（门禁本体）。
    direct = route("get_venue_operation", ec, card="project_fit")
    assert direct["allowed"] is False
    assert direct["readiness_tag"] == "SYNTHETIC"

    out = await run_skill(state)

    assert run_guard["called"] is False
    warehouse.get_rest.assert_not_called()
    assert out["skill_result"].data["readiness_tag"] == "SYNTHETIC"
    assert "SYNTHETIC" in out["answer"]
    # readiness 拦截归类为 DATA_NOT_CONNECTED（非 scope），readiness=NOT_CONNECTED。
    assert out["error"] == "DATA_NOT_CONNECTED"
    assert out["skill_result"].readiness == Readiness.NOT_CONNECTED


# ===== roadmap 阶段1 #10 第二句「每条接口必须标注，缺标注则拒绝接入」=====
# 旧行为是 fail-open：catalog 里没写 readiness 的接口落到 readiness_tag="UNKNOWN"，
# 而门禁只拦 "SYNTHETIC" ⇒ 没标注 = 自动放行。实测这 4 个无标注接口恰是写操作
# （create_lead / delete_lead / confirm_lead / reject_lead）。


def test_unannotated_write_tool_denied_in_production(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "PRODUCTION")
    direct = route("create_lead", ctx())
    assert direct["allowed"] is False, direct
    assert direct["readiness_tag"] == "UNKNOWN"
    assert "未标注" in direct["reason"]


def test_unannotated_tool_still_routed_outside_production(monkeypatch):
    """fail-closed 只作用于生产档；DEV/DEMO 不设新障碍（渐进开启，不误伤本地与 CI）。"""
    monkeypatch.setenv("AGENT_MODE", "DEMO")
    direct = route("create_lead", ctx())
    assert direct["allowed"] is True, direct
    assert direct["readiness_tag"] == "UNKNOWN"


# 门禁只作用于命中 _CATALOG_ROUTE 的 skill：data_analysis.query 跳过 route 仍正常执行。
async def test_run_skill_data_analysis_skips_catalog_route(monkeypatch, mock_nl2sql_success):
    monkeypatch.setattr(metric_registry, "get_metric_status", lambda mid: "VERIFIED")
    calls = _spy_route(monkeypatch)
    ec = ctx()
    state = _state(
        ec=ec,
        warehouse_client=_blocking_warehouse(),  # data_analysis 不应触达 warehouse
        params={"metric_id": "exhibitor_count", "nl_query": "参展商数量"},
        skill_name="data_analysis.query",
    )

    out = await run_skill(state)

    # 不在 catalog 映射表 → 不经 route()，也不触达 WarehouseClient。
    assert calls == []
    assert out["skill_result"] is not None
    assert out["skill_result"].readiness == Readiness.READY
