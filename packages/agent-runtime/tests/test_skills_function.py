"""FunctionExecutor 单元测试：as_function_skill 包装 + 契约。"""

from __future__ import annotations

import pytest

from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import SkillKind


@pytest.mark.asyncio
async def test_as_function_skill_basic():
    """as_function_skill 包装 async 函数为 FUNCTION 型 Skill。"""
    async def add(a, b):
        return a + b

    skill = as_function_skill("add", "加法", add)
    assert skill.name == "add"
    assert skill.description == "加法"
    assert skill.kind == SkillKind.FUNCTION
    result = await skill.executor(a=1, b=2)
    assert result == 3


@pytest.mark.asyncio
async def test_as_function_skill_with_schema():
    """as_function_skill 传递 input/output schema。"""
    async def search(query):
        return f"result for {query}"

    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    skill = as_function_skill("search", "搜索", search, input_schema=schema)
    assert skill.input_schema == schema
    assert skill.output_schema is None


@pytest.mark.asyncio
async def test_as_function_skill_with_timeout():
    """as_function_skill 设置 timeout_ms。"""
    async def fast():
        return "ok"

    skill = as_function_skill("fast", "快速", fast, timeout_ms=5000)
    assert skill.timeout_ms == 5000


def test_as_function_skill_permissions():
    """as_function_skill 设置 permissions。"""
    async def privileged():
        return "secret"

    skill = as_function_skill("priv", "特权", privileged, permissions={"admin"})
    assert "admin" in skill.permissions


@pytest.mark.asyncio
async def test_as_function_skill_kwargs_passthrough():
    """executor 接受任意 kwargs 透传给 fn。"""
    async def multi(a, b, c, d=0):
        return a * b * c + d

    skill = as_function_skill("multi", "乘加", multi)
    result = await skill.executor(a=2, b=3, c=4, d=5)
    assert result == 29
