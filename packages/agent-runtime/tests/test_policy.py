"""PolicyValidator 单元测试：五项校验闸门（无环/深度/步数/能力注册/权限）。"""

from __future__ import annotations

import pytest

from agent_runtime.planner.execution_graph import ExecutionGraph
from agent_runtime.planner.policy import PlanViolationError, PolicyValidator
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import SkillRegistry


def _make_registry() -> SkillRegistry:
    reg = SkillRegistry()

    async def search(query):
        return f"result for {query}"

    async def analyze(text):
        return f"analyzed {text}"

    async def privileged_op(data):
        return "secret"

    reg.register(as_function_skill("search", "搜索", search))
    reg.register(as_function_skill("analyze", "分析", analyze))
    reg.register(as_function_skill("privileged", "特权操作", privileged_op, permissions={"admin"}))
    return reg


def _make_simple_graph() -> ExecutionGraph:
    g = ExecutionGraph()
    g.add_node("a", "search", {"query": "test"})
    g.add_node("b", "analyze", {})
    g.add_edge("b", "a")
    return g


def test_validate_passes_simple_graph():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = _make_simple_graph()
    result = pv.validate(g)
    assert result is g


def test_validate_detects_cycle():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "search")
    g.add_node("b", "analyze")
    g.add_edge("b", "a")
    g.add_edge("a", "b")
    with pytest.raises(PlanViolationError, match="循环依赖"):
        pv.validate(g)


def test_validate_depth_exceeds():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("n0", "search")
    for i in range(1, 6):
        g.add_node(f"n{i}", "analyze")
        g.add_edge(f"n{i}", f"n{i - 1}")
    with pytest.raises(PlanViolationError, match="深度"):
        pv.validate(g, max_depth=3)


def test_validate_steps_exceeds():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    for i in range(25):
        g.add_node(f"n{i}", "search")
    with pytest.raises(PlanViolationError, match="步数"):
        pv.validate(g, max_steps=20)


def test_validate_parallel_exceeds():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    for i in range(5):
        g.add_node(f"n{i}", "search")
    with pytest.raises(PlanViolationError, match="并行度"):
        pv.validate(g, max_parallel=3)


def test_validate_unregistered_skill():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "nonexistent_skill")
    with pytest.raises(PlanViolationError, match="未注册能力"):
        pv.validate(g)


def test_validate_permission_denied():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "privileged")
    with pytest.raises(PlanViolationError, match="权限"):
        pv.validate(g, caller_permissions={"read"})


def test_validate_permission_granted():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "privileged")
    result = pv.validate(g, caller_permissions={"admin", "read"})
    assert result is g


def test_validate_permission_empty_means_public():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "search")
    result = pv.validate(g, caller_permissions=set())
    assert result is g


def test_validate_aggregates_multiple_violations():
    reg = _make_registry()
    pv = PolicyValidator(reg)
    g = ExecutionGraph()
    for i in range(25):
        g.add_node(f"n{i}", "nonexistent")
    with pytest.raises(PlanViolationError) as exc_info:
        pv.validate(g, max_steps=20)
    msg = str(exc_info.value)
    assert "步数" in msg
    assert "未注册能力" in msg
