"""ExecutionGraph 边界测试：环检测/拓扑分层/深度/步数。"""

from __future__ import annotations

import pytest

from agent_runtime.planner.execution_graph import ExecutionGraph, GraphCycleError


def test_add_node_duplicate_raises():
    g = ExecutionGraph()
    g.add_node("a", "search")
    with pytest.raises(ValueError, match="节点已存在"):
        g.add_node("a", "search")


def test_add_edge_unknown_node_raises():
    g = ExecutionGraph()
    g.add_node("a", "search")
    with pytest.raises(ValueError, match="未知节点"):
        g.add_edge("a", "nonexistent")
    with pytest.raises(ValueError, match="未知节点"):
        g.add_edge("nonexistent", "a")


def test_add_edge_self_loop_raises():
    g = ExecutionGraph()
    g.add_node("a", "search")
    with pytest.raises(GraphCycleError, match="自环"):
        g.add_edge("a", "a")


def test_detect_cycle_no_cycle():
    g = ExecutionGraph()
    g.add_node("a", "search")
    g.add_node("b", "analyze")
    g.add_edge("b", "a")
    assert g.detect_cycle() is False


def test_detect_cycle_simple():
    g = ExecutionGraph()
    g.add_node("a", "search")
    g.add_node("b", "analyze")
    g.add_edge("b", "a")
    g.add_edge("a", "b")
    assert g.detect_cycle() is True


def test_detect_cycle_three_node():
    g = ExecutionGraph()
    g.add_node("a", "s")
    g.add_node("b", "s")
    g.add_node("c", "s")
    g.add_edge("b", "a")
    g.add_edge("c", "b")
    g.add_edge("a", "c")
    assert g.detect_cycle() is True


def test_topological_layers_simple():
    g = ExecutionGraph()
    g.add_node("a", "search")
    g.add_node("b", "analyze")
    g.add_edge("b", "a")
    layers = g.topological_layers()
    assert layers == [["a"], ["b"]]


def test_topological_layers_parallel():
    g = ExecutionGraph()
    g.add_node("a", "search")
    g.add_node("b", "search")
    g.add_node("c", "analyze")
    g.add_edge("c", "a")
    g.add_edge("c", "b")
    layers = g.topological_layers()
    assert layers[0] == ["a", "b"]
    assert layers[1] == ["c"]


def test_topological_layers_cycle_raises():
    g = ExecutionGraph()
    g.add_node("a", "s")
    g.add_node("b", "s")
    g.add_edge("b", "a")
    g.add_edge("a", "b")
    with pytest.raises(GraphCycleError):
        g.topological_layers()


def test_max_depth_chain():
    g = ExecutionGraph()
    g.add_node("n0", "s")
    for i in range(1, 5):
        g.add_node(f"n{i}", "s")
        g.add_edge(f"n{i}", f"n{i - 1}")
    assert g.max_depth() == 5


def test_max_depth_empty():
    g = ExecutionGraph()
    assert g.max_depth() == 0


def test_max_depth_parallel():
    g = ExecutionGraph()
    g.add_node("a", "s")
    g.add_node("b", "s")
    assert g.max_depth() == 1


def test_step_count():
    g = ExecutionGraph()
    for i in range(5):
        g.add_node(f"n{i}", "s")
    assert g.step_count() == 5


def test_nodes_property():
    g = ExecutionGraph()
    g.add_node("a", "search", {"query": "test"})
    nodes = g.nodes
    assert "a" in nodes
    assert nodes["a"].skill_name == "search"


def test_edges_property():
    g = ExecutionGraph()
    g.add_node("a", "s")
    g.add_node("b", "s")
    g.add_edge("b", "a")
    edges = g.edges
    assert "a" in edges["b"]
