"""PolicyValidator 测试（Plan-F 策略校验）：循环/深度/步数/权限/未注册能力。"""

from __future__ import annotations

import pytest
from agent_runtime.planner.execution_graph import ExecutionGraph
from agent_runtime.planner.policy import PlanViolationError, PolicyValidator
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


async def _noop(**kwargs):
    return None


def _skill(name: str, permissions: set[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description=name,
        kind=SkillKind.FUNCTION,
        executor=_noop,
        permissions=frozenset(permissions) if permissions else frozenset(),
    )


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(_skill("public_skill"))
    reg.register(_skill("admin_skill", permissions={"admin"}))
    return reg


# ---------- 校验通过 ----------


def test_validate_passes():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "public_skill")
    g.add_node("b", "public_skill")
    g.add_edge("b", "a")
    result = validator.validate(g, max_depth=4, max_steps=20)
    assert result is g


def test_validate_empty_graph_passes():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    validator.validate(g)


# ---------- 循环 ----------


def test_validate_cycle_rejected():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "public_skill")
    g.add_node("b", "public_skill")
    g.add_edge("b", "a")
    g.add_edge("a", "b")
    with pytest.raises(PlanViolationError, match="循环"):
        validator.validate(g)


# ---------- 深度上限 ----------


def test_validate_depth_exceeded():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "public_skill")
    g.add_node("b", "public_skill")
    g.add_node("c", "public_skill")
    g.add_edge("b", "a")
    g.add_edge("c", "b")
    with pytest.raises(PlanViolationError, match="深度"):
        validator.validate(g, max_depth=2)


# ---------- 步数上限 ----------


def test_validate_steps_exceeded():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    for i in range(5):
        g.add_node(f"n{i}", "public_skill")
    with pytest.raises(PlanViolationError, match="步数"):
        validator.validate(g, max_steps=3)


# ---------- 未注册能力 ----------


def test_validate_unregistered_skill():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "nonexistent_skill")
    with pytest.raises(PlanViolationError, match="未注册"):
        validator.validate(g)


# ---------- 权限 ----------


def test_validate_permissions_denied():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "admin_skill")
    with pytest.raises(PlanViolationError, match="权限"):
        validator.validate(g, caller_permissions={"read"})


def test_validate_permissions_allowed():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "admin_skill")
    validator.validate(g, caller_permissions={"admin", "read"})


def test_validate_permissions_none_skips_check():
    """caller_permissions=None 时跳过权限校验（向后兼容）。"""
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "admin_skill")
    validator.validate(g)


# ---------- 多违规聚合 ----------


def test_validate_multiple_violations():
    reg = _registry()
    validator = PolicyValidator(reg)
    g = ExecutionGraph()
    g.add_node("a", "admin_skill")
    g.add_node("b", "nonexistent")
    with pytest.raises(PlanViolationError) as exc_info:
        validator.validate(g, max_steps=1, caller_permissions={"read"})
    msg = str(exc_info.value)
    assert "步数" in msg or "权限" in msg or "未注册" in msg
