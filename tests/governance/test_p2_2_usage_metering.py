"""P2-2：llm client 计量点验证。

覆盖：
- ``FallbackChatModel`` 从 LangChain AIMessage（usage_metadata / response_metadata）抽取 token 数；
- invoke / ainvoke / stream / astream 路径均经 ``on_usage`` 回调外发 usage；
- ``PlannerRuntime`` 装配期把 llm 的 ``on_usage`` 接到当前 ExecutionContext（contextvars 隔离），
  执行边界内累计 tokens_used，边界外静默丢弃；status 事件带出累计 tokens。
"""

from __future__ import annotations

import asyncio

import pytest


class _UsageMsg:
    def __init__(self, content, usage_metadata=None, response_metadata=None):
        self.content = content
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


class _UsageModel:
    """最小模型替身：返回带 usage 的响应（同步/异步/流）。"""

    def __init__(self, msg):
        self._msg = msg

    def invoke(self, *a, **k):
        return self._msg

    async def ainvoke(self, *a, **k):
        return self._msg

    def stream(self, *a, **k):
        yield self._msg

    async def astream(self, *a, **k):
        yield self._msg


def _fallback_with(msg, on_usage=None):
    from agent_core.llm.fallback import FallbackChatModel

    return FallbackChatModel(_UsageModel(msg), _UsageModel(msg), on_usage=on_usage)


def test_extract_usage_from_usage_metadata():
    from agent_core.llm.fallback import FallbackChatModel

    msg = _UsageMsg("x", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    assert FallbackChatModel._extract_usage(msg) == 15


def test_extract_usage_from_response_metadata():
    from agent_core.llm.fallback import FallbackChatModel

    msg = _UsageMsg("x", response_metadata={"usage": {"prompt_tokens": 3, "completion_tokens": 7}})
    assert FallbackChatModel._extract_usage(msg) == 10


def test_extract_usage_missing_returns_zero():
    from agent_core.llm.fallback import FallbackChatModel

    assert FallbackChatModel._extract_usage(_UsageMsg("x")) == 0


def test_invoke_emits_usage():
    collected = []
    m = _fallback_with(
        _UsageMsg("x", usage_metadata={"total_tokens": 12}), on_usage=lambda t, c: collected.append((t, c))
    )
    assert m.invoke("q").content == "x"
    assert collected == [(12, 0.0)]


def test_ainvoke_emits_usage():
    collected = []
    m = _fallback_with(
        _UsageMsg("x", usage_metadata={"total_tokens": 8}), on_usage=lambda t, c: collected.append((t, c))
    )
    assert asyncio.run(m.ainvoke("q")).content == "x"
    assert collected == [(8, 0.0)]


def test_stream_emits_usage_on_last_chunk():
    from agent_core.llm.fallback import FallbackChatModel

    collected = []

    class _ChunkModel:
        def invoke(self, *a, **k):
            raise AssertionError("unexpected")

        async def ainvoke(self, *a, **k):
            raise AssertionError("unexpected")

        def stream(self, *a, **k):
            # 中段 chunk 无 usage，末段 chunk 带累计 total
            yield _UsageMsg("p0")
            yield _UsageMsg("p1", usage_metadata={"total_tokens": 20})

        async def astream(self, *a, **k):
            yield _UsageMsg("p0")
            yield _UsageMsg("p1", usage_metadata={"total_tokens": 20})

    m = FallbackChatModel(_ChunkModel(), _ChunkModel(), on_usage=lambda t, c: collected.append((t, c)))
    assert [c.content for c in m.stream("q")] == ["p0", "p1"]
    assert collected == [(20, 0.0)]


@pytest.mark.asyncio
async def test_astream_emits_usage():
    from agent_core.llm.fallback import FallbackChatModel

    collected = []

    class _ChunkModel:
        def stream(self, *a, **k):
            yield _UsageMsg("p0")

        async def astream(self, *a, **k):
            yield _UsageMsg("p0")
            yield _UsageMsg("p1", usage_metadata={"total_tokens": 9})

    m = FallbackChatModel(_ChunkModel(), _ChunkModel(), on_usage=lambda t, c: collected.append((t, c)))
    chunks = [c async for c in m.astream("q")]
    assert [c.content for c in chunks] == ["p0", "p1"]
    assert collected == [(9, 0.0)]


# ---------- 装配方：PlannerRuntime 接线 ----------


class _FakeLLM:
    """替身 llm：支持 set_on_usage，ainvoke 产出后调用 on_usage（模拟 FallbackChatModel）。"""

    def __init__(self):
        self.on_usage = None

    def set_on_usage(self, callback):
        self.on_usage = callback

    async def ainvoke(self, *a, **k):
        msg = _UsageMsg("llm", usage_metadata={"total_tokens": 17})
        if self.on_usage is not None:
            self.on_usage(17, 0.0)
        return msg


@pytest.mark.asyncio
async def test_runtime_wires_usage_into_execution_context():
    from agent_runtime.planner.protocol import PlannerRuntime

    llm = _FakeLLM()
    runtime = PlannerRuntime(registry=None, llm=llm, max_tokens=100)

    # 装配期已把 llm.on_usage 接到 runtime._on_llm_usage
    assert llm.on_usage is not None

    async with runtime.execution():
        await llm.ainvoke("q")  # 触发 usage 上报
        assert runtime.context.tokens_used == 17
        assert runtime.context.cost_used == 0.0


@pytest.mark.asyncio
async def test_usage_outside_execution_scope_is_silently_dropped():
    from agent_runtime.planner.protocol import PlannerRuntime

    llm = _FakeLLM()
    runtime = PlannerRuntime(registry=None, llm=llm)
    # 不在 execution() 边界内：回调静默丢弃，不报错、不污染
    await llm.ainvoke("q")
    assert runtime.context is None


@pytest.mark.asyncio
async def test_status_event_carries_accumulated_tokens():
    from agent_runtime.planner.execution_graph import execute_plan
    from agent_runtime.planner.protocol import Plan, PlannerRuntime

    class _FakeRegistry:
        async def execute(self, name, **kwargs):
            return ["证据"]

    llm = _FakeLLM()
    runtime = PlannerRuntime(registry=_FakeRegistry(), llm=llm, max_tokens=100)
    plan = Plan(route="search", sub_query="q", notes={"question": "q", "workspace_id": "default"})

    events = [ev async for ev in execute_plan(plan, runtime)]
    status = next(ev for ev in events if ev.type == "status")
    # 执行过程中 LLM 被调用（合成/压缩等）累计 tokens；无 LLM 调用时应为 0
    assert "tokens_used" in status.payload
    assert "cost_used" in status.payload
    assert isinstance(status.payload["tokens_used"], int)
