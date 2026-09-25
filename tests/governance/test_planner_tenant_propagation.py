"""治理红线：所有已注册 Planner 的 plan() 全路径必须保留 tenant_id 身份。

背景（2026-09-24 tenant isolation 评审 Critical#2）：``Plan.tenant_id`` 默认
``"default"``，构造时漏传不报错、静默落共享桶——多真实租户经同一 workspace_id
时记忆互不可见/互可见。本测试枚举各 Planner 实现及其主要 return 分支，断言
``plan(ctx).tenant_id == ctx.tenant_id``，防止未来新增分支漏传导致回归。

红线语义：任何新增 ``return Plan(...)`` 分支若不透传 ctx.tenant_id，此测试必红。
"""

from types import SimpleNamespace

import pytest
from agent_runtime.planner.agentic import AgenticPlanner
from agent_runtime.planner.mode_selector import ExecutionMode, ModeDecision
from agent_runtime.planner.protocol import PlannerContext
from agent_server.config import get_settings
from agent_server.planners.deterministic import DeterministicPlanner
from agent_server.planners.graph import GraphPlanner
from agent_server.planners.unified import UnifiedPlanner

# 非 "default" 的哨兵租户：漏传会落 default 桶，断言即可捕获
TENANT = "tenant-gov-42"
WORKSPACE = "ws-gov"
USER = "u-gov"


def _ctx(question: str = "你好呀") -> PlannerContext:
    return PlannerContext(
        question=question, workspace_id=WORKSPACE, user_id=USER, tenant_id=TENANT
    )


class _FakeRegistry:
    """最小 registry 替身：discover 返回固定候选（GraphPlanner / ModeSelector 只用到此方法）。"""

    def __init__(self, names=("rag",)):
        self._names = tuple(names)

    def discover(self, query, top_k=10, kinds=None):
        return [SimpleNamespace(name=n) for n in self._names]


class _FakeSelector:
    def __init__(self, decision: ModeDecision):
        self._decision = decision

    async def select(self, ctx, registry):
        return self._decision


def _assert_identity(plan, *, with_kwargs: bool = False) -> None:
    assert plan.tenant_id == TENANT, f"Plan 丢失租户身份（落入了 {plan.tenant_id!r} 桶）"
    assert plan.workspace_id == WORKSPACE
    assert plan.user_id == USER
    if with_kwargs:
        # workflow 单 route delegate 直接消费 plan.kwargs，身份须随附
        assert plan.kwargs.get("tenant_id") == TENANT
        assert plan.kwargs.get("workspace_id") == WORKSPACE


@pytest.mark.asyncio
async def test_deterministic_planner_propagates_tenant():
    plan = await DeterministicPlanner().plan(_ctx())
    _assert_identity(plan)


@pytest.mark.asyncio
async def test_graph_planner_no_registry_fallback_propagates_tenant():
    plan = await GraphPlanner(registry=None).plan(_ctx())
    _assert_identity(plan)


@pytest.mark.asyncio
async def test_graph_planner_no_candidates_fallback_propagates_tenant():
    plan = await GraphPlanner(registry=_FakeRegistry(names=())).plan(_ctx())
    _assert_identity(plan)


@pytest.mark.asyncio
async def test_graph_planner_single_node_propagates_tenant():
    # ctx.llm 为 None → 单节点分支（_single_node_plan）
    plan = await GraphPlanner(registry=_FakeRegistry(("rag",))).plan(_ctx())
    _assert_identity(plan)


@pytest.mark.asyncio
async def test_agentic_planner_propagates_tenant():
    plan = await AgenticPlanner().plan(_ctx())
    _assert_identity(plan)


@pytest.mark.asyncio
async def test_unified_planner_workflow_branch_propagates_tenant():
    """WORKFLOW 分支重建 Plan（覆盖子 Planner 产物），身份与 delegate kwargs 都必须透传。"""
    selector = _FakeSelector(
        ModeDecision(
            mode=ExecutionMode.WORKFLOW,
            reason="test",
            workflow_skill="general_qa",
        )
    )
    planner = UnifiedPlanner(
        get_settings(), registry=_FakeRegistry(), selector=selector
    )
    plan = await planner.plan(_ctx())
    assert plan.mode == "workflow"
    _assert_identity(plan, with_kwargs=True)


@pytest.mark.asyncio
async def test_unified_planner_delegates_with_tenant():
    """非 workflow 分支：UnifiedPlanner 透传子 Planner 产物，不得丢身份。"""
    for mode in (ExecutionMode.DETERMINISTIC, ExecutionMode.GRAPH):
        selector = _FakeSelector(ModeDecision(mode=mode, reason="test"))
        planner = UnifiedPlanner(
            get_settings(), registry=_FakeRegistry(), selector=selector
        )
        plan = await planner.plan(_ctx())
        assert plan.tenant_id == TENANT, f"{mode.value} 路径丢失租户身份"
