"""LLM 可观测后端抽象测试（C 方案：接口先行，实现渐进）。

验证：
1. Protocol 定义（runtime_checkable）
2. NoOpBackend：get_callbacks 返回空 + 未来方法 NotImplementedError
3. LangfuseBackend：SDK 未安装降级 no-op + 未来方法 NotImplementedError
4. LangSmithBackend：get_callbacks 返回列表 + 未来方法 NotImplementedError
5. factory：按名返回正确后端 + 未知名降级 noop + 缓存
6. 集成：run_supervisor callbacks=None / [] 均正常
"""

from __future__ import annotations

import pytest

from exhibition_agent.graph.supervisor import run_supervisor
from exhibition_agent.observability.llm_obs import (
    LangfuseBackend,
    LangSmithBackend,
    LLMObsBackend,
    NoOpBackend,
    get_llm_obs_backend,
    reset_backend_cache,
)
from exhibition_agent.observability.trace import InMemoryTraceRecorder
from exhibition_agent.testing_helpers import ctx, ctx_header


# ---------------------------------------------------------------------------
# 1. Protocol
# ---------------------------------------------------------------------------
def test_protocol_is_runtime_checkable():
    """LLMObsBackend 是 runtime_checkable Protocol（isinstance 可判）。"""
    assert isinstance(NoOpBackend(), LLMObsBackend)
    assert isinstance(LangfuseBackend(), LLMObsBackend)
    assert isinstance(LangSmithBackend(), LLMObsBackend)


def test_all_backends_have_name():
    """每个后端都有 name 属性。"""
    assert NoOpBackend().name == "noop"
    assert LangfuseBackend().name == "langfuse"
    assert LangSmithBackend().name == "langsmith"


# ---------------------------------------------------------------------------
# 2. NoOpBackend
# ---------------------------------------------------------------------------
def test_noop_get_callbacks_returns_empty():
    backend = NoOpBackend()
    assert backend.get_callbacks() == []


def test_noop_future_methods_raise_not_implemented():
    backend = NoOpBackend()
    with pytest.raises(NotImplementedError, match="eval"):
        backend.eval("test", [])
    with pytest.raises(NotImplementedError, match="prompt"):
        backend.log_prompt("p", "template")
    with pytest.raises(NotImplementedError, match="dataset"):
        backend.create_dataset("d")
    with pytest.raises(NotImplementedError, match="score"):
        backend.score("run-1", "acc", 0.95)


# ---------------------------------------------------------------------------
# 3. LangfuseBackend（SDK 未安装 → no-op 降级）
# ---------------------------------------------------------------------------
def test_langfuse_get_callbacks_returns_list():
    """langfuse SDK 未安装时 get_callbacks 返回空列表（no-op 降级不崩）。"""
    backend = LangfuseBackend()
    callbacks = backend.get_callbacks()
    assert isinstance(callbacks, list)


def test_langfuse_future_methods_raise_not_implemented():
    backend = LangfuseBackend()
    with pytest.raises(NotImplementedError, match="Langfuse eval"):
        backend.eval("test", [])
    with pytest.raises(NotImplementedError, match="Langfuse prompt"):
        backend.log_prompt("p", "template")
    with pytest.raises(NotImplementedError, match="Langfuse dataset"):
        backend.create_dataset("d")
    with pytest.raises(NotImplementedError, match="Langfuse score"):
        backend.score("run-1", "acc", 0.95)


# ---------------------------------------------------------------------------
# 4. LangSmithBackend（已移除 langchain 依赖，降级为 no-op 行为）
# ---------------------------------------------------------------------------
def test_langsmith_get_callbacks_returns_list():
    """LangSmith 后端已移除 langchain 依赖，get_callbacks 恒返回空列表。"""
    backend = LangSmithBackend()
    callbacks = backend.get_callbacks()
    assert callbacks == []


def test_langsmith_future_methods_raise_not_implemented():
    backend = LangSmithBackend()
    with pytest.raises(NotImplementedError, match="LangSmith 后端已移除"):
        backend.eval("test", [])
    with pytest.raises(NotImplementedError, match="LangSmith 后端已移除"):
        backend.log_prompt("p", "template")
    with pytest.raises(NotImplementedError, match="LangSmith 后端已移除"):
        backend.create_dataset("d")
    with pytest.raises(NotImplementedError, match="LangSmith 后端已移除"):
        backend.score("run-1", "acc", 0.95)


# ---------------------------------------------------------------------------
# 5. factory
# ---------------------------------------------------------------------------
def test_factory_returns_correct_backend():
    reset_backend_cache()
    assert isinstance(get_llm_obs_backend("noop"), NoOpBackend)
    reset_backend_cache()
    assert isinstance(get_llm_obs_backend("langfuse"), LangfuseBackend)
    reset_backend_cache()
    assert isinstance(get_llm_obs_backend("langsmith"), LangSmithBackend)


def test_factory_unknown_name_falls_back_to_noop():
    reset_backend_cache()
    backend = get_llm_obs_backend("unknown_backend")
    assert isinstance(backend, NoOpBackend)


def test_factory_caches_by_name():
    reset_backend_cache()
    b1 = get_llm_obs_backend("noop")
    b2 = get_llm_obs_backend("noop")
    assert b1 is b2


def test_factory_cache_invalidates_on_name_change():
    reset_backend_cache()
    b1 = get_llm_obs_backend("noop")
    b2 = get_llm_obs_backend("langfuse")
    assert b1 is not b2
    assert isinstance(b1, NoOpBackend)
    assert isinstance(b2, LangfuseBackend)


def test_reset_backend_cache():
    b1 = get_llm_obs_backend("noop")
    reset_backend_cache()
    b2 = get_llm_obs_backend("noop")
    assert b1 is not b2


# ---------------------------------------------------------------------------
# 6. 集成：run_supervisor callbacks 参数
# ---------------------------------------------------------------------------
async def test_run_supervisor_with_none_callbacks(warehouse_client):
    """callbacks=None → 正常运行（测试默认路径，不接入 LLM 可观测）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆排期",
        "params": {"venue_id": "vn-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    }, callbacks=None)
    assert state["skill_result"] is not None


async def test_run_supervisor_with_empty_callbacks(warehouse_client):
    """callbacks=[] → 正常运行（空列表不崩）。"""
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆排期",
        "params": {"venue_id": "vn-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    }, callbacks=[])
    assert state["skill_result"] is not None


async def test_run_supervisor_with_noop_callbacks(warehouse_client):
    """callbacks=NoOpBackend().get_callbacks() → 正常运行。"""
    reset_backend_cache()
    backend = get_llm_obs_backend("noop")
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆排期",
        "params": {"venue_id": "vn-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    }, callbacks=backend.get_callbacks() or None)
    assert state["skill_result"] is not None


async def test_run_supervisor_with_langfuse_callbacks(warehouse_client):
    """callbacks=LangfuseBackend().get_callbacks() → 正常运行（SDK 未安装时为空列表）。"""
    reset_backend_cache()
    backend = get_llm_obs_backend("langfuse")
    context = ctx()
    state = await run_supervisor({
        "query": "查询场馆排期",
        "params": {"venue_id": "vn-001"},
        "execution_context": context,
        "execution_context_header": ctx_header(context),
        "context_mode": "jwt",
        "warehouse_client": warehouse_client,
        "trace_recorder": InMemoryTraceRecorder(),
        "sql_statements": [],
        "extra_headers": {"X-Mock-Scenario": "normal_200"},
    }, callbacks=backend.get_callbacks() or None)
    assert state["skill_result"] is not None
