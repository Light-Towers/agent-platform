"""ExecutionGraph 测试（Plan-F 动态执行图）：DAG 结构 + 分层并行执行。"""

from __future__ import annotations

import pytest
from agent_runtime.planner.execution_graph import (
    ExecutionGraph,
    GraphCycleError,
    execute_graph,
)
from agent_runtime.planner.protocol import PlannerRuntime


class _RecordingRegistry:
    """记录调用顺序的注册表替身。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, name: str, **kwargs):
        self.calls.append(name)
        return f"result:{name}"


# ---------- DAG 结构 ----------


def test_add_node_and_edge():
    g = ExecutionGraph()
    g.add_node("a", "web_search", {"query": "x"})
    g.add_node("b", "analyze")
    g.add_edge("b", "a")
    assert set(g.nodes) == {"a", "b"}
    assert g.edges["b"] == {"a"}


def test_add_edge_unknown_node_raises():
    g = ExecutionGraph()
    g.add_node("a", "skill")
    with pytest.raises(ValueError, match="未知节点"):
        g.add_edge("a", "nonexistent")
    with pytest.raises(ValueError, match="未知节点"):
        g.add_edge("nonexistent", "a")


def test_self_loop_raises():
    g = ExecutionGraph()
    g.add_node("a", "skill")
    with pytest.raises(GraphCycleError, match="自环"):
        g.add_edge("a", "a")


# ---------- 循环检测 ----------


def test_detect_cycle_false():
    g = ExecutionGraph()
    g.add_node("a", "s1")
    g.add_node("b", "s2")
    g.add_edge("b", "a")
    assert g.detect_cycle() is False


def test_detect_cycle_true():
    g = ExecutionGraph()
    g.add_node("a", "s1")
    g.add_node("b", "s2")
    g.add_edge("b", "a")
    g.add_edge("a", "b")
    assert g.detect_cycle() is True


# ---------- 分层拓扑 ----------


def test_topological_layers_sequential():
    g = ExecutionGraph()
    g.add_node("a", "s1")
    g.add_node("b", "s2")
    g.add_edge("b", "a")
    assert g.topological_layers() == [["a"], ["b"]]


def test_topological_layers_parallel():
    """同层无依赖的节点在同一层（可并行）。"""
    g = ExecutionGraph()
    g.add_node("a", "s1")
    g.add_node("b", "s2")
    g.add_node("c", "s3")
    g.add_edge("c", "a")
    g.add_edge("c", "b")
    layers = g.topological_layers()
    assert layers[0] == ["a", "b"]
    assert layers[1] == ["c"]


def test_topological_layers_cycle_raises():
    g = ExecutionGraph()
    g.add_node("a", "s1")
    g.add_node("b", "s2")
    g.add_edge("b", "a")
    g.add_edge("a", "b")
    with pytest.raises(GraphCycleError):
        g.topological_layers()


def test_max_depth_and_step_count():
    g = ExecutionGraph()
    g.add_node("a", "s1")
    g.add_node("b", "s2")
    g.add_node("c", "s3")
    g.add_edge("b", "a")
    g.add_edge("c", "b")
    assert g.max_depth() == 3
    assert g.step_count() == 3


def test_empty_graph_depth_zero():
    g = ExecutionGraph()
    assert g.max_depth() == 0
    assert g.step_count() == 0


# ---------- execute_graph ----------


@pytest.mark.asyncio
async def test_execute_graph_sequential():
    """顺序依赖图：a → b，a 先执行。"""
    reg = _RecordingRegistry()
    runtime = PlannerRuntime(registry=reg)
    g = ExecutionGraph()
    g.add_node("a", "web_search", {"query": "x"})
    g.add_node("b", "analyze")
    g.add_edge("b", "a")

    events = [ev async for ev in execute_graph(g, runtime)]

    assert [e.type for e in events] == ["evidence", "evidence", "answer"]
    assert events[0].payload["node"] == "a"
    assert events[1].payload["node"] == "b"
    assert events[2].payload["results"]["a"] == "result:web_search"


@pytest.mark.asyncio
async def test_execute_graph_parallel_layer():
    """同层节点并行执行，均产出 evidence 事件。"""
    reg = _RecordingRegistry()
    runtime = PlannerRuntime(registry=reg)
    g = ExecutionGraph()
    g.add_node("a", "search_a")
    g.add_node("b", "search_b")
    g.add_node("c", "synthesis")
    g.add_edge("c", "a")
    g.add_edge("c", "b")

    events = [ev async for ev in execute_graph(g, runtime)]

    evidence_events = [e for e in events if e.type == "evidence"]
    layer0 = {e.payload["node"] for e in evidence_events if e.payload["layer"] == 0}
    layer1 = {e.payload["node"] for e in evidence_events if e.payload["layer"] == 1}
    assert layer0 == {"a", "b"}
    assert layer1 == {"c"}
    assert reg.calls.count("search_a") == 1
    assert reg.calls.count("search_b") == 1
