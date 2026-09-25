"""Durability（Phase E）测试：ExecutionGraph 执行级 checkpoint / resume。

验证 doc §11 与架构验收 #10：执行失败可通过 checkpoint/resume 诊断或恢复——已完成节点
结果复用、未完成任务继续（尊重依赖边），不重跑已完成节点。
"""

from __future__ import annotations

from agent_runtime.planner.durability import (
    Checkpoint,
    InMemoryCheckpointStore,
    new_execution_id,
)
from agent_runtime.planner.execution_graph import (
    ExecutionGraph,
    _run_graph_in_place,
)
from agent_runtime.planner.protocol import PlannerRuntime
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


class _Boom(Exception):
    pass


async def _fetch(**kwargs):
    return {"summary": f"searched:{kwargs.get('query')}"}


async def _analyze(**kwargs):
    return {"report": f"analyzed:{kwargs.get('data')}"}


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill("web_search", "联网搜索 web search", SkillKind.FUNCTION, _fetch))
    reg.register(Skill("analyze", "分析数据 analyze data", SkillKind.FUNCTION, _analyze))
    return reg


def _graph() -> ExecutionGraph:
    g = ExecutionGraph()
    g.add_node("n1", "web_search", {"query": "$query"})
    g.add_node("n2", "analyze", input_refs={"data": "node:n1"})
    g.add_edge("n2", "n1")
    return g


async def test_checkpoint_resume_after_failure():
    store = InMemoryCheckpointStore()
    exec_id = new_execution_id()

    # 第一次执行：n2 的 analyze 抛错（模拟崩溃），n1 已完成并落 checkpoint
    async def _boom_analyze(**kwargs):
        raise _Boom("crash")

    reg = SkillRegistry()
    reg.register(Skill("web_search", "联网搜索 web search", SkillKind.FUNCTION, _fetch))
    reg.register(Skill("analyze", "分析数据 analyze data", SkillKind.FUNCTION, _boom_analyze))
    runtime = PlannerRuntime(registry=reg)

    # 第一次执行：n2 的 analyze 抛错（节点级隔离 → 仅产出 error 事件，不中断整次执行）；
    # n1 已完成并落 checkpoint。
    async with runtime.execution():
        async for ev in _run_graph_in_place(
            _graph(), runtime, checkpoint_store=store, execution_id=exec_id
        ):
            pass

    # n1 已完成并 checkpoint；n2 因失败未落盘
    cp = await store.load(exec_id)
    assert cp is not None
    assert "n1" in cp.completed
    assert "n2" not in cp.completed

    # resume：用修复后的 registry（analyze 正常），同一 exec_id → n1 不复跑，n2 继续
    runtime2 = PlannerRuntime(registry=_registry())
    results: dict = {}
    async with runtime2.execution():
        async for ev in _run_graph_in_place(
            _graph(), runtime2, checkpoint_store=store, execution_id=exec_id
        ):
            if ev.type == "answer":
                results = ev.payload["results"]
    # n1 复用 checkpoint 结果，n2 用 n1 输出正常完成
    assert results["n1"] == {"summary": "searched:$query"}
    assert results["n2"] == {"report": "analyzed:{'summary': 'searched:$query'}"}


async def test_checkpoint_store_roundtrip():
    store = InMemoryCheckpointStore()
    cp = Checkpoint("e1", {"n1": {"x": 1}})
    await store.save(cp)
    loaded = await store.load("e1")
    assert loaded is not None
    assert loaded.completed == {"n1": {"x": 1}}
    assert await store.load("missing") is None
