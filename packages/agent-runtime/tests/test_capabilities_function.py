"""FunctionExecutor 单元测试：as_function_capability 包装 + 契约。"""

from __future__ import annotations

import pytest

from agent_runtime.capabilities.function import as_function_capability
from agent_runtime.capabilities.registry import CapabilityKind


@pytest.mark.asyncio
async def test_as_function_capability_basic():
    """as_function_capability 包装 async 函数为 FUNCTION 型 Capability。"""
    async def add(a, b):
        return a + b

    capability = as_function_capability("add", "加法", add)
    assert capability.name == "add"
    assert capability.description == "加法"
    assert capability.kind == CapabilityKind.FUNCTION
    result = await capability.executor(a=1, b=2)
    assert result == 3


@pytest.mark.asyncio
async def test_as_function_capability_with_schema():
    """as_function_capability 传递 input/output schema。"""
    async def search(query):
        return f"result for {query}"

    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    capability = as_function_capability("search", "搜索", search, input_schema=schema)
    assert capability.input_schema == schema
    assert capability.output_schema is None


@pytest.mark.asyncio
async def test_as_function_capability_with_timeout():
    """as_function_capability 设置 timeout_ms。"""
    async def fast():
        return "ok"

    capability = as_function_capability("fast", "快速", fast, timeout_ms=5000)
    assert capability.timeout_ms == 5000


def test_as_function_capability_permissions():
    """as_function_capability 设置 permissions。"""
    async def privileged():
        return "secret"

    capability = as_function_capability("priv", "特权", privileged, permissions={"admin"})
    assert "admin" in capability.permissions


@pytest.mark.asyncio
async def test_as_function_capability_kwargs_passthrough():
    """executor 接受任意 kwargs 透传给 fn。"""
    async def multi(a, b, c, d=0):
        return a * b * c + d

    capability = as_function_capability("multi", "乘加", multi)
    result = await capability.executor(a=2, b=3, c=4, d=5)
    assert result == 29
