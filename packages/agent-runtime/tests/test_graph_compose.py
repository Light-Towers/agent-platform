"""Dynamic Graph 组合（Phase B）测试：parse_graph_json 校验 + compose_execution_graph（fake LLM）。"""

from __future__ import annotations

import pytest
from agent_runtime.planner.execution_graph import ExecutionGraph
from agent_runtime.planner.graph_compose import (
    GraphComposeError,
    compose_execution_graph,
    parse_graph_json,
)
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(
        Skill("web_search", "联网搜索 web search", SkillKind.FUNCTION, _echo, metadata={"kind": "function"})
    )
    reg.register(
        Skill("analyze", "分析数据 analyze data", SkillKind.FUNCTION, _echo, metadata={"kind": "function"})
    )
    return reg


async def _echo(**kwargs):
    return kwargs


def _cands(reg: SkillRegistry):
    return reg.discover("搜索 分析", top_k=10)


def test_parse_single_node():
    g = parse_graph_json(
        {"nodes": [{"id": "n1", "skill": "web_search", "inputs": {"query": "$query"}}]},
        "北京天气",
        {"web_search", "analyze"},
    )
    assert isinstance(g, ExecutionGraph)
    assert "n1" in g.nodes
    assert g.nodes["n1"].kwargs["query"] == "北京天气"


def test_parse_multi_node_with_edge_and_ref():
    data = {
        "nodes": [
            {"id": "n1", "skill": "web_search", "inputs": {"query": "$query"}},
            {"id": "n2", "skill": "analyze", "inputs": {"data": "$node.n1"}},
        ],
        "edges": [{"dependent": "n2", "dependency": "n1"}],
    }
    g = parse_graph_json(data, "北京天气", {"web_search", "analyze"})
    assert g.nodes["n2"].input_refs["data"] == "node:n1"
    assert not g.detect_cycle()


def test_parse_rejects_out_of_scope_skill():
    with pytest.raises(GraphComposeError):
        parse_graph_json(
            {"nodes": [{"id": "n1", "skill": "hacker", "inputs": {}}]},
            "q",
            {"web_search"},
        )


def test_parse_rejects_cycle():
    data = {
        "nodes": [
            {"id": "n1", "skill": "web_search", "inputs": {}},
            {"id": "n2", "skill": "analyze", "inputs": {}},
        ],
        "edges": [
            {"dependent": "n2", "dependency": "n1"},
            {"dependent": "n1", "dependency": "n2"},
        ],
    }
    with pytest.raises(GraphComposeError):
        parse_graph_json(data, "q", {"web_search", "analyze"})


def test_parse_rejects_missing_nodes():
    with pytest.raises(GraphComposeError):
        parse_graph_json({"edges": []}, "q", {"web_search"})


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def ainvoke(self, messages):
        import json

        return type("R", (), {"content": json.dumps(self._payload)})()


async def test_compose_via_llm():
    reg = _registry()
    payload = {
        "nodes": [
            {"id": "n1", "skill": "web_search", "inputs": {"query": "$query"}},
            {"id": "n2", "skill": "analyze", "inputs": {"data": "$node.n1"}},
        ],
        "edges": [{"dependent": "n2", "dependency": "n1"}],
    }
    g = await compose_execution_graph("北京天气", _cands(reg), _FakeLLM(payload))
    assert isinstance(g, ExecutionGraph)
    assert len(g.nodes) == 2
    assert g.nodes["n2"].input_refs["data"] == "node:n1"


async def test_compose_rejects_non_json():
    reg = _registry()

    class _BadLLM:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "not json"})()

    with pytest.raises(GraphComposeError):
        await compose_execution_graph("q", _cands(reg), _BadLLM())
