"""Capability Registry 单元测试（Plan-F Phase 1）。

覆盖：注册/发现/统一执行入口、重复注册保护、未知能力报错、超时边界、
三执行器工厂（function 执行 / agent 包装结构 / remote 执行）。
"""

from __future__ import annotations

import asyncio

import pytest
from agent_runtime.skills.agent import as_agent_skill
from agent_runtime.skills.dag import as_dag_skill
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import (
    DuplicateSkillError,
    SkillKind,
    SkillNotFoundError,
    SkillRegistry,
)
from agent_runtime.skills.remote import as_remote_skill


@pytest.mark.asyncio
async def test_function_capability_execute():
    async def add(a: int, b: int) -> int:
        return a + b

    registry = SkillRegistry()
    registry.register(as_function_skill("add", "加法", add))

    assert registry.get("add").kind == SkillKind.FUNCTION
    assert "add" in registry
    assert await registry.execute("add", a=1, b=2) == 3


def test_duplicate_register_raises():
    async def noop(**kwargs):
        return None

    registry = SkillRegistry()
    registry.register(as_function_skill("a", "A", noop))
    with pytest.raises(DuplicateSkillError):
        registry.register(as_function_skill("a", "A2", noop))


@pytest.mark.asyncio
async def test_execute_unknown_raises():
    registry = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        await registry.execute("nope")


def test_list_sorted():
    async def noop(**kwargs):
        return None

    registry = SkillRegistry()
    for name in ("b", "a", "c"):
        registry.register(as_function_skill(name, name, noop))
    assert [c.name for c in registry.list()] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_timeout_applies():
    async def slow(**kwargs):
        await asyncio.sleep(5)
        return "late"

    registry = SkillRegistry()
    registry.register(as_function_skill("slow", "慢", slow, timeout_ms=50))
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
    cap = as_agent_skill(subagent)
    assert cap.name == "database_query_agent"
    assert cap.kind == SkillKind.AGENT
    assert cap.description == "数据库查询"


@pytest.mark.asyncio
async def test_remote_capability_execute():
    async def invoke(**kwargs):
        return f"remote:{kwargs['q']}"

    registry = SkillRegistry()
    registry.register(as_remote_skill("remote_search", "远程搜索", invoke))
    assert await registry.execute("remote_search", q="x") == "remote:x"


# ---------- Phase 1.5：Skill 契约（input/output JSON Schema） ----------


def test_capability_input_output_schema():
    async def add(a: int, b: int) -> int:
        return a + b

    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    cap = as_function_skill(
        "add", "加法", add, input_schema=schema, output_schema={"type": "integer"}
    )
    assert cap.input_schema == schema
    assert cap.output_schema == {"type": "integer"}


def test_to_tool_schema():
    async def noop(**kwargs):
        return None

    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    cap = as_function_skill("search", "搜索", noop, input_schema=schema)
    tool = cap.to_tool_schema()
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "search"
    assert tool["function"]["description"] == "搜索"
    assert tool["function"]["parameters"] == schema


def test_to_tool_schema_default_empty_params():
    async def noop(**kwargs):
        return None

    cap = as_function_skill("x", "X", noop)
    assert cap.to_tool_schema()["function"]["parameters"] == {"type": "object", "properties": {}}


# ---------- Phase 3：Static DAG Executor（Workflow Skill） ----------


@pytest.mark.asyncio
async def test_dag_capability_execute():
    async def run_dag(**kwargs):
        return f"answer:{kwargs['question']}"

    cap = as_dag_skill(
        "general_qa",
        "通用问答",
        run_dag,
        input_schema={"type": "object", "required": ["question"]},
        timeout_ms=5000,
    )
    assert cap.kind == SkillKind.WORKFLOW
    assert cap.timeout_ms == 5000
    registry = SkillRegistry()
    registry.register(cap)
    assert await registry.execute("general_qa", question="你好") == "answer:你好"


@pytest.mark.asyncio
async def test_build_registry_with_graph_registers_general_qa():
    """app 侧装配：注入 graph 后注册 general_qa Workflow Skill（graph 包装而非删除）。"""
    from app.capabilities import build_registry

    class FakeGraph:
        async def astream(self, state, config=None, stream_mode="updates"):
            yield {"synthesize": {"answer": f"答:{state['question']}"}}

    registry = build_registry(graph=FakeGraph())
    names = [c.name for c in registry.list()]
    assert "general_qa" in names
    cap = registry.get("general_qa")
    assert cap.kind == SkillKind.WORKFLOW
    answer = await registry.execute(
        "general_qa", question="你好", workspace_id="default", user_id="default", thread_id="t"
    )
    assert answer == "答:你好"


def test_build_registry_without_graph_no_general_qa():
    from app.capabilities import build_registry

    registry = build_registry()
    assert [c.name for c in registry.list()] == ["mcp", "rag", "search", "sql"]
