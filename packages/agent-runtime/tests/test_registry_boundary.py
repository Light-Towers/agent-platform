"""SkillRegistry 边界测试：注册/发现/执行/契约校验。"""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import (
    DuplicateSkillError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillRegistry,
)


def _reg_with_skills() -> SkillRegistry:
    reg = SkillRegistry()

    async def search(query):
        return f"result:{query}"

    async def analyze(text):
        return f"analyzed:{text}"

    reg.register(as_function_skill("search", "搜索数据", search))
    reg.register(as_function_skill("analyze", "分析内容", analyze))
    return reg


def test_register_duplicate_raises():
    reg = SkillRegistry()

    async def fn1():
        return 1

    reg.register(as_function_skill("dup", "第一个", fn1))
    with pytest.raises(DuplicateSkillError):
        reg.register(as_function_skill("dup", "第二个", fn1))


def test_get_not_found_raises():
    reg = _reg_with_skills()
    with pytest.raises(SkillNotFoundError):
        reg.get("nonexistent")


def test_contains():
    reg = _reg_with_skills()
    assert "search" in reg
    assert "nonexistent" not in reg


def test_list_sorted_by_name():
    reg = _reg_with_skills()
    skills = reg.list()
    names = [s.name for s in skills]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_execute_input_validation_missing_required():
    reg = SkillRegistry()

    async def fn(query):
        return query

    schema = {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}
    reg.register(as_function_skill("search", "搜索", fn, input_schema=schema))
    with pytest.raises(SkillExecutionError, match="缺少必填参数"):
        await reg.execute("search")


@pytest.mark.asyncio
async def test_execute_input_validation_wrong_type():
    reg = SkillRegistry()

    async def fn(query):
        return query

    schema = {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}
    reg.register(as_function_skill("search", "搜索", fn, input_schema=schema))
    with pytest.raises(SkillExecutionError, match="期望 string"):
        await reg.execute("search", query=123)


@pytest.mark.asyncio
async def test_execute_timeout():
    reg = SkillRegistry()

    async def slow():
        await asyncio.sleep(10)
        return "done"

    reg.register(as_function_skill("slow", "慢操作", slow, timeout_ms=50))
    with pytest.raises(asyncio.TimeoutError):
        await reg.execute("slow")


@pytest.mark.asyncio
async def test_execute_output_validation():
    reg = SkillRegistry()

    async def fn():
        return 123

    schema = {"type": "string"}
    reg.register(as_function_skill("fn", "测试", fn, output_schema=schema))
    with pytest.raises(SkillExecutionError, match="期望 string"):
        await reg.execute("fn")


def test_discover_permission_filter():
    reg = SkillRegistry()

    async def public_fn():
        return 1

    async def admin_fn():
        return 2

    reg.register(as_function_skill("public", "公开", public_fn))
    reg.register(as_function_skill("admin", "管理", admin_fn, permissions={"admin"}))
    results = reg.discover(caller_permissions={"read"})
    names = [s.name for s in results]
    assert "public" in names
    assert "admin" not in names


def test_discover_metadata_filter():
    reg = SkillRegistry()

    async def fn1():
        return 1

    skill1 = as_function_skill("s1", "技能1", fn1)
    skill2 = as_function_skill("s2", "技能2", fn1)

    from agent_runtime.skills.registry import Skill, SkillKind

    skill2 = Skill(
        name="s2", description="技能2", kind=SkillKind.FUNCTION,
        executor=skill1.executor, metadata={"source": "external"},
    )
    reg.register(skill1)
    reg.register(skill2)
    results = reg.discover(metadata_filter={"source": "external"})
    assert len(results) == 1
    assert results[0].name == "s2"


def test_discover_keyword_scoring():
    reg = _reg_with_skills()
    results = reg.discover("搜索")
    assert results[0].name == "search"


def test_discover_top_k():
    reg = _reg_with_skills()
    results = reg.discover(top_k=1)
    assert len(results) == 1
