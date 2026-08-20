"""动态执行图（Plan-F）：Planner 产出的 Skill 组合计划，Runtime 校验后分层并行执行。

与静态 DAG（``agent_server/agent/graph.py`` 编译期固定拓扑）的区别：ExecutionGraph
由 Planner 在决策期动态构建——节点是 Skill 调用，边是依赖关系（``dependent → dependency``
表示 dependency 须先完成）。``PolicyValidator`` 校验无环 / 深度 / 步数 / 权限后，
``execute_graph`` 按拓扑分层并行执行（同层 ``asyncio.gather``，层间顺序）。

架构契约：Planner 负责「提出计划」（构建 ExecutionGraph），Runtime 负责「验证 + 执行」
（PolicyValidator + execute_graph）——不把执行自由度完全交给 LLM。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_runtime.planner.protocol import StreamEvent

if TYPE_CHECKING:
    from agent_runtime.planner.protocol import PlannerRuntime


@dataclass(frozen=True)
class GraphNode:
    """执行图节点：一次 Skill 调用。"""

    node_id: str
    skill_name: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class GraphCycleError(ValueError):
    """执行图存在循环依赖，无法分层排序。"""


class ExecutionGraph:
    """动态执行图：节点（Skill 调用）+ 依赖边（``dependent → dependency``，dependency 先执行）。

    用法::

        g = ExecutionGraph()
        g.add_node("a", "web_search", {"query": "..."})
        g.add_node("b", "analyze", {})
        g.add_edge("b", "a")  # b 依赖 a，a 先执行
        layers = g.topological_layers()  # [["a"], ["b"]]

    同层节点无依赖关系，可 ``asyncio.gather`` 并行执行。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        # node_id -> 前置依赖集合（dependent -> {dependencies}）
        self._deps: dict[str, set[str]] = {}

    def add_node(
        self, node_id: str, skill_name: str, kwargs: dict[str, Any] | None = None
    ) -> GraphNode:
        """添加节点：node_id 唯一，skill_name 为注册表中的能力名。"""
        if node_id in self._nodes:
            raise ValueError(f"节点已存在: {node_id}")
        node = GraphNode(node_id, skill_name, kwargs or {})
        self._nodes[node_id] = node
        self._deps.setdefault(node_id, set())
        return node

    def add_edge(self, dependent: str, dependency: str) -> None:
        """声明依赖：``dependent`` 依赖 ``dependency``（dependency 先执行）。"""
        if dependent not in self._nodes or dependency not in self._nodes:
            raise ValueError(f"未知节点: {dependent} 或 {dependency}")
        if dependent == dependency:
            raise GraphCycleError(f"自环依赖: {dependent}")
        self._deps[dependent].add(dependency)

    @property
    def nodes(self) -> dict[str, GraphNode]:
        """全部节点（只读拷贝）。"""
        return dict(self._nodes)

    @property
    def edges(self) -> dict[str, set[str]]:
        """全部依赖边（只读拷贝）。"""
        return {k: set(v) for k, v in self._deps.items()}

    def detect_cycle(self) -> bool:
        """检测是否存在循环依赖（DFS 三色标记法）。"""
        white, gray, black = 0, 1, 2
        color = {nid: white for nid in self._nodes}

        def dfs(nid: str) -> bool:
            color[nid] = gray
            for dep in self._deps[nid]:
                if color[dep] == gray:
                    return True
                if color[dep] == white and dfs(dep):
                    return True
            color[nid] = black
            return False

        return any(color[nid] == white and dfs(nid) for nid in self._nodes)

    def topological_layers(self) -> list[list[str]]:
        """分层拓扑排序：同层节点无依赖关系，可并行执行。

        返回 ``list[layer]``，layer 是 node_id 列表（按名排序保证确定性）。
        第 0 层无依赖，第 i 层依赖第 <i 层。存在循环时抛 ``GraphCycleError``。
        """
        if self.detect_cycle():
            raise GraphCycleError("执行图存在循环依赖，无法分层排序")
        remaining = set(self._nodes)
        completed: set[str] = set()
        layers: list[list[str]] = []
        while remaining:
            layer = sorted(nid for nid in remaining if self._deps[nid] <= completed)
            if not layer:
                raise GraphCycleError("执行图存在循环依赖（分层求解失败）")
            layers.append(layer)
            completed |= set(layer)
            remaining -= set(layer)
        return layers

    def max_depth(self) -> int:
        """图的最大依赖链深度（层数，空图为 0）。"""
        return len(self.topological_layers()) if self._nodes else 0

    def step_count(self) -> int:
        """总节点数（Skill 调用步数）。"""
        return len(self._nodes)


async def execute_graph(
    graph: ExecutionGraph,
    runtime: PlannerRuntime,
) -> AsyncIterator[StreamEvent]:
    """分层并行执行 ExecutionGraph：同层 ``asyncio.gather``，层间顺序执行。

    每个节点经 ``runtime.delegate()`` 调用 Skill（受 ``skill_guard`` 组合治理，
    计入步数 / 深度 / 循环预算）。产出 ``StreamEvent``：

    - 每节点完成产出 ``evidence`` 事件（含 node_id / skill / layer / result）；
    - 全部完成产出 ``answer`` 事件（聚合全部节点结果 dict）。

    须在 ``runtime.execution()`` 边界内调用（delegate 前置校验）。
    """
    layers = graph.topological_layers()
    results: dict[str, Any] = {}
    for i, layer in enumerate(layers):

        async def _run(node_id: str) -> tuple[str, Any]:
            node = graph.nodes[node_id]
            return node_id, await runtime.delegate(node.skill_name, **node.kwargs)

        layer_results = await asyncio.gather(*(_run(nid) for nid in layer))
        for node_id, result in layer_results:
            results[node_id] = result
            yield StreamEvent(
                type="evidence",
                payload={
                    "node": node_id,
                    "skill": graph.nodes[node_id].skill_name,
                    "layer": i,
                    "result": result,
                },
            )
    yield StreamEvent(type="answer", payload={"results": results})
