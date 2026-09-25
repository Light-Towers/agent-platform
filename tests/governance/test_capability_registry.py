"""Capability Registry 单元测试（Plan-F Phase 1）。

覆盖：注册/发现/统一执行入口、重复注册保护、未知能力报错、超时边界、
三执行器工厂（function 执行 / agent 包装结构 / remote 执行）。
"""

from __future__ import annotations

import asyncio

import pytest
from agent_runtime.circuit_breaker import CircuitBreaker
from agent_runtime.skills.agent import as_agent_skill
from agent_runtime.skills.dag import as_dag_skill
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.middleware import CircuitBreakerMiddleware
from agent_runtime.skills.registry import (
    DuplicateSkillError,
    SkillExecutionError,
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
    from agent_server.capabilities import build_registry

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
    from agent_server.capabilities import build_registry

    registry = build_registry()
    assert [c.name for c in registry.list()] == ["mcp", "rag", "search", "sql"]


# ---------- 架构审核 P1：Skill 契约真正执行（入参校验） ----------


@pytest.mark.asyncio
async def test_execute_validates_required_input():
    """缺少 required 参数时抛 SkillExecutionError（而非内部异常）。"""
    async def run(**kwargs):
        return "ok"

    registry = SkillRegistry()
    registry.register(
        as_function_skill(
            "search",
            "搜索",
            run,
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        )
    )
    with pytest.raises(SkillExecutionError, match="缺少必填参数"):
        await registry.execute("search")


@pytest.mark.asyncio
async def test_execute_validates_input_type():
    """参数类型不符时抛 SkillExecutionError（明确契约错误而非内部异常）。"""
    async def run(**kwargs):
        return "ok"

    registry = SkillRegistry()
    registry.register(
        as_function_skill(
            "search",
            "搜索",
            run,
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        )
    )
    with pytest.raises(SkillExecutionError, match="期望 string"):
        await registry.execute("search", q=123)


@pytest.mark.asyncio
async def test_execute_skips_validation_without_schema():
    """无 schema 时保持原透传行为（向后兼容）。"""
    async def run(**kwargs):
        return kwargs

    registry = SkillRegistry()
    registry.register(as_function_skill("x", "X", run))
    assert await registry.execute("x", anything=1) == {"anything": 1}


# ---------- Phase 架构审核：Skill Execution Middleware 洋葱链 ----------


class _RecordingMiddleware:
    """记录 call 顺序的测试中间件（外层先 after，内层先 before）。"""

    def __init__(self, name: str, events: list[str], delay_enter: bool = False):
        self._name = name
        self._events = events
        self._delay_enter = delay_enter

    async def around(self, name, kwargs, call_next):
        if self._delay_enter:
            self._events.append(f"before:{self._name}")
            return await call_next(name, kwargs)
        self._events.append(f"before:{self._name}")
        result = await call_next(name, kwargs)
        self._events.append(f"after:{self._name}")
        return result


class _ShortCircuitMiddleware:
    """不调用 call_next 即短路（拦截语义）。"""

    async def around(self, name, kwargs, call_next):
        return "short-circuited"


@pytest.mark.asyncio
async def test_middleware_onion_order():
    """洋葱链顺序：先注册的外层先执行前置，后执行后置（LIFO after）。"""
    events: list[str] = []

    async def run(**kwargs):
        events.append("execute")
        return "ok"

    registry = SkillRegistry(
        middlewares=[
            _RecordingMiddleware("outer", events),
            _RecordingMiddleware("inner", events),
        ]
    )
    registry.register(as_function_skill("x", "X", run))

    assert await registry.execute("x") == "ok"
    assert events == ["before:outer", "before:inner", "execute", "after:inner", "after:outer"]


@pytest.mark.asyncio
async def test_middleware_short_circuit_skips_executor():
    """中间件不调用 call_next 即短路，执行器不执行。"""
    called = []

    async def run(**kwargs):
        called.append(1)
        return "ok"

    registry = SkillRegistry(middlewares=[_ShortCircuitMiddleware()])
    registry.register(as_function_skill("x", "X", run))

    assert await registry.execute("x") == "short-circuited"
    assert called == []


@pytest.mark.asyncio
async def test_middleware_chain_with_timeout_still_applies():
    """超时边界仍在最内层执行器上生效（中间件包裹执行器，不绕过超时）。"""
    import asyncio as _asyncio

    events: list[str] = []

    async def slow(**kwargs):
        events.append("execute")
        await _asyncio.sleep(5)
        return "late"

    registry = SkillRegistry(
        middlewares=[_RecordingMiddleware("mw", events, delay_enter=True)]
    )
    registry.register(as_function_skill("slow", "慢", slow, timeout_ms=50))

    with pytest.raises(_asyncio.TimeoutError):
        await registry.execute("slow")
    assert events == ["before:mw", "execute"]


@pytest.mark.asyncio
async def test_circuit_breaker_middleware_degrades():
    """熔断中间件：打开后不再调用执行器，返回降级消息（与 search 原内嵌行为等价）。"""
    calls = []

    async def run(**kwargs):
        calls.append(1)
        raise RuntimeError("上游故障")

    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    registry = SkillRegistry(
        middlewares=[CircuitBreakerMiddleware(breaker, skill_names=("search",))]
    )
    registry.register(as_function_skill("search", "搜索", run))
    registry.register(as_function_skill("rag", "RAG", run))

    # 首次失败触发熔断（breaker.call fallback=None → 降级消息）
    degraded = await registry.execute("search", q="x")
    assert degraded == ["联网搜索暂时不可用（熔断或请求失败）"]
    # 熔断打开后短路：执行器不再被调用
    await registry.execute("search", q="x")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_circuit_breaker_middleware_scope():
    """skill_names 限定故障域：search 熔断不影响 rag（同 breaker 但不同技能）。"""
    calls = []

    async def run(**kwargs):
        calls.append(kwargs.get("skill"))
        raise RuntimeError("boom")

    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    registry = SkillRegistry(
        middlewares=[CircuitBreakerMiddleware(breaker, skill_names=("search",))]
    )
    registry.register(as_function_skill("search", "搜索", run))
    registry.register(as_function_skill("rag", "RAG", run))

    await registry.execute("search", q="x")
    with pytest.raises(RuntimeError):
        # rag 不在熔断范围内：异常直接透传（熔断仅包裹 search）
        await registry.execute("rag", q="y")
    assert calls == [None, None]


# ---------- output_schema 校验 ----------


@pytest.mark.asyncio
async def test_execute_validates_output_type_string():
    async def run(**kwargs):
        return 123  # 期望 string，返回 int

    registry = SkillRegistry()
    registry.register(
        as_function_skill(
            "search", "搜索", run, output_schema={"type": "string"}
        )
    )
    with pytest.raises(SkillExecutionError, match="产出校验失败"):
        await registry.execute("search")


@pytest.mark.asyncio
async def test_execute_validates_output_object_required():
    async def run(**kwargs):
        return {"b": 1}  # 缺 required 字段 a

    registry = SkillRegistry()
    registry.register(
        as_function_skill(
            "search",
            "搜索",
            run,
            output_schema={"type": "object", "required": ["a"]},
        )
    )
    with pytest.raises(SkillExecutionError, match="缺少必填字段"):
        await registry.execute("search")


@pytest.mark.asyncio
async def test_execute_output_schema_passes():
    async def run(**kwargs):
        return {"answer": "ok"}

    registry = SkillRegistry()
    registry.register(
        as_function_skill(
            "search",
            "搜索",
            run,
            output_schema={"type": "object", "required": ["answer"]},
        )
    )
    result = await registry.execute("search")
    assert result == {"answer": "ok"}


@pytest.mark.asyncio
async def test_execute_no_output_schema_skips_validation():
    async def run(**kwargs):
        return 123  # 无 output_schema，不校验

    registry = SkillRegistry()
    registry.register(as_function_skill("x", "X", run))
    assert await registry.execute("x") == 123
