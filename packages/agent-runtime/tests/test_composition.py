"""Skill → Skill 一等公民组合模型（§7.1）CompositionValidator 测试。"""

from __future__ import annotations

import pytest
from agent_runtime.skills.composition import CompositionError, CompositionValidator
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


async def _noop(**kwargs):
    return {}


def _reg_with_composition():
    reg = SkillRegistry()
    reg.register(Skill("a", "A", SkillKind.FUNCTION, _noop, sub_skills=("b",)))
    reg.register(Skill("b", "B", SkillKind.FUNCTION, _noop, sub_skills=()))
    return reg


async def test_valid_composition_passes():
    reg = _reg_with_composition()
    assert CompositionValidator(reg).validate() == []


async def test_missing_sub_skill_detected():
    reg = SkillRegistry()
    reg.register(Skill("a", "A", SkillKind.FUNCTION, _noop, sub_skills=("ghost",)))
    v = CompositionValidator(reg).validate()
    assert any("ghost" in msg for msg in v)


async def test_cycle_detected():
    reg = SkillRegistry()
    reg.register(Skill("a", "A", SkillKind.FUNCTION, _noop, sub_skills=("b",)))
    reg.register(Skill("b", "B", SkillKind.FUNCTION, _noop, sub_skills=("a",)))
    v = CompositionValidator(reg).validate()
    assert any("成环" in msg for msg in v)


async def test_permission_closure_enforced():
    reg = SkillRegistry()
    # a 只有 p；b 需要 p+q → a 组合 b 时权限未闭合
    reg.register(
        Skill("a", "A", SkillKind.FUNCTION, _noop, permissions=frozenset({"p"}),
              sub_skills=("b",))
    )
    reg.register(
        Skill("b", "B", SkillKind.FUNCTION, _noop, permissions=frozenset({"p", "q"}))
    )
    v = CompositionValidator(reg).validate()
    assert any("权限" in msg for msg in v)


async def test_permission_closure_ok():
    reg = SkillRegistry()
    reg.register(
        Skill("a", "A", SkillKind.FUNCTION, _noop, permissions=frozenset({"p", "q"}),
              sub_skills=("b",))
    )
    reg.register(
        Skill("b", "B", SkillKind.FUNCTION, _noop, permissions=frozenset({"p"}))
    )
    assert CompositionValidator(reg).validate() == []


async def test_assert_valid_raises():
    reg = SkillRegistry()
    reg.register(Skill("a", "A", SkillKind.FUNCTION, _noop, sub_skills=("ghost",)))
    with pytest.raises(CompositionError):
        CompositionValidator(reg).assert_valid()
