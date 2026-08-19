"""Capability Registry 单元测试（Plan-F Phase 1）。

覆盖：注册/发现/统一执行入口、重复注册保护、未知能力报错、超时边界、
三执行器工厂（function 执行 / agent 包装结构 / remote 执行）。
"""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.capabilities.agent import as_agent_capability
from agent_runtime.capabilities.function import as_function_capability
from agent_runtime.capabilities.registry import (
    CapabilityKind,
    CapabilityNotFoundError,
    CapabilityRegistry,
    DuplicateCapabilityError,
)
from agent_runtime.capabilities.remote import as_remote_capability


@pytest.mark.asyncio
async def test_function_capability_execute():
    async def add(a: int, b: int) -> int:
        return a + b

    registry = CapabilityRegistry()
    registry.register(as_function_capability("add", "加法", add))

    assert registry.get("add").kind == CapabilityKind.FUNCTION
    assert "add" in registry
    assert await registry.execute("add", a=1, b=2) == 3


def test_duplicate_register_raises():
    async def noop(**kwargs):
        return None

    registry = CapabilityRegistry()
    registry.register(as_function_capability("a", "A", noop))
    with pytest.raises(DuplicateCapabilityError):
        registry.register(as_function_capability("a", "A2", noop))


@pytest.mark.asyncio
async def test_execute_unknown_raises():
    registry = CapabilityRegistry()
    with pytest.raises(CapabilityNotFoundError):
        await registry.execute("nope")


def test_list_sorted():
    async def noop(**kwargs):
        return None

    registry = CapabilityRegistry()
    for name in ("b", "a", "c"):
        registry.register(as_function_capability(name, name, noop))
    assert [c.name for c in registry.list()] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_timeout_applies():
    async def slow(**kwargs):
        await asyncio.sleep(5)
        return "late"

    registry = CapabilityRegistry()
    registry.register(as_function_capability("slow", "慢", slow, timeout_ms=50))
    with pytest.raises(asyncio.TimeoutError):
        await registry.execute("slow")


def test_agent_capability_shape():
    """AgentExecutor：subagent dict 包装为 agent 型能力（不实际调用 LLM）。"""
    subagent = {
        "name": "database_query_agent",
        "description": "数据库查询",
        "system_prompt": "你是数据库专家",
        "tools": [lambda: None],
    }
    cap = as_agent_capability(subagent)
    assert cap.name == "database_query_agent"
    assert cap.kind == CapabilityKind.AGENT
    assert cap.description == "数据库查询"


@pytest.mark.asyncio
async def test_remote_capability_execute():
    async def invoke(**kwargs):
        return f"remote:{kwargs['q']}"

    registry = CapabilityRegistry()
    registry.register(as_remote_capability("remote_search", "远程搜索", invoke))
    assert await registry.execute("remote_search", q="x") == "remote:x"
