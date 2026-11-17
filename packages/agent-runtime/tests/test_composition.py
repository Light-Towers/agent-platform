"""Capability → Capability 一等公民组合模型（§7.1）CompositionValidator 测试。"""

from __future__ import annotations

import pytest

from agent_runtime.capabilities.composition import CompositionError, CompositionValidator
from agent_runtime.capabilities.registry import Capability, CapabilityKind, CapabilityRegistry


async def _noop(**kwargs):
    return {}


def _reg_with_composition():
    reg = CapabilityRegistry()
    reg.register(Capability("a", "A", CapabilityKind.FUNCTION, _noop, sub_capabilities=("b",)))
    reg.register(Capability("b", "B", CapabilityKind.FUNCTION, _noop, sub_capabilities=()))
    return reg


async def test_valid_composition_passes():
    reg = _reg_with_composition()
    assert CompositionValidator(reg).validate() == []


async def test_missing_sub_capability_detected():
    reg = CapabilityRegistry()
    reg.register(Capability("a", "A", CapabilityKind.FUNCTION, _noop, sub_capabilities=("ghost",)))
    v = CompositionValidator(reg).validate()
    assert any("ghost" in msg for msg in v)


async def test_cycle_detected():
    reg = CapabilityRegistry()
    reg.register(Capability("a", "A", CapabilityKind.FUNCTION, _noop, sub_capabilities=("b",)))
    reg.register(Capability("b", "B", CapabilityKind.FUNCTION, _noop, sub_capabilities=("a",)))
    v = CompositionValidator(reg).validate()
    assert any("成环" in msg for msg in v)


async def test_permission_closure_enforced():
    reg = CapabilityRegistry()
    # a 只有 p；b 需要 p+q → a 组合 b 时权限未闭合
    reg.register(
        Capability("a", "A", CapabilityKind.FUNCTION, _noop, permissions=frozenset({"p"}),
              sub_capabilities=("b",))
    )
    reg.register(
        Capability("b", "B", CapabilityKind.FUNCTION, _noop, permissions=frozenset({"p", "q"}))
    )
    v = CompositionValidator(reg).validate()
    assert any("权限" in msg for msg in v)


async def test_permission_closure_ok():
    reg = CapabilityRegistry()
    reg.register(
        Capability("a", "A", CapabilityKind.FUNCTION, _noop, permissions=frozenset({"p", "q"}),
              sub_capabilities=("b",))
    )
    reg.register(
        Capability("b", "B", CapabilityKind.FUNCTION, _noop, permissions=frozenset({"p"}))
    )
    assert CompositionValidator(reg).validate() == []


async def test_assert_valid_raises():
    reg = CapabilityRegistry()
    reg.register(Capability("a", "A", CapabilityKind.FUNCTION, _noop, sub_capabilities=("ghost",)))
    with pytest.raises(CompositionError):
        CompositionValidator(reg).assert_valid()
