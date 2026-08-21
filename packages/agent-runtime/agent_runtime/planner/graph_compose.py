"""Dynamic Graph 组合器（完整架构 Phase B）：候选 Skill → LLM 输出结构化多 Skill DAG IR。

架构契约（docs/complete-agent-runtime-architecture.md §4.4）：
- LLM 只允许从候选 Skill（经 ``SkillRegistry.discover`` 缩窄）中选择，输出结构化 Graph IR；
- 禁止模型生成任意 Python / 任意执行器（仅 ``skill`` 引用 + 输入映射 + 依赖边）；
- 组合产物为平台级 ``ExecutionGraph`` IR，交由 PolicyValidator 校验 + Runtime 执行。

输入映射（``inputs``）语义（LLM 输出约定）：
- ``"$query"``：替换为原始问题字符串（组合期静态替换）；
- ``"$node.<node_id>"``：引用上游节点输出（执行期动态解析，写入 ``input_refs``）；
- 其他值视为字面量透传。

模块分两层，便于测试：
- ``parse_graph_json``：纯函数，把 LLM 产出的 dict 解析为 ``ExecutionGraph``（含校验，
  失败时抛 ``GraphComposeError``）；
- ``compose_execution_graph``：组装 prompt → 调 LLM → ``parse_graph_json``。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.planner.execution_graph import ExecutionGraph

_QUERY_TOKEN = "$query"
_NODE_REF_PREFIX = "$node."


class GraphComposeError(ValueError):
    """LLM 产出的 Graph IR 非法（节点/边/引用校验失败）。"""


def _substitute(value: Any, question: str) -> tuple[Any, str | None]:
    """解析单个输入值：``$query`` 替换为问题；``$node.<id>`` 返回 (原值, ref)；否则字面量。"""
    if isinstance(value, str):
        if value == _QUERY_TOKEN:
            return question, None
        if value.startswith(_NODE_REF_PREFIX):
            return value, value[len(_NODE_REF_PREFIX) :]
    return value, None


def parse_graph_json(
    data: dict[str, Any],
    question: str,
    candidate_names: set[str],
) -> ExecutionGraph:
    """把 LLM 产出的 Graph IR dict 解析为 ``ExecutionGraph``。

    :param data: ``{"nodes": [...], "edges": [...]}``；节点形如
        ``{"id": "n1", "skill": "web_search", "inputs": {"query": "$query"}}``；
        边形如 ``{"dependent": "n2", "dependency": "n1"}``。
    :param question: 原始问题，用于 ``$query`` 替换。
    :param candidate_names: 候选能力名集合（LLM 只能从中选择），越界抛 GraphComposeError。
    :raises GraphComposeError: 节点缺失 / skill 越界 / 引用未知节点 / 结构非法。
    """
    if not isinstance(data, dict):
        raise GraphComposeError("Graph IR 必须是对象")
    nodes_raw = data.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise GraphComposeError("Graph IR 至少需要一个节点（nodes）")

    g = ExecutionGraph()
    seen: set[str] = set()
    for n in nodes_raw:
        if not isinstance(n, dict):
            raise GraphComposeError(f"节点必须是对象: {n!r}")
        node_id = n.get("id")
        skill = n.get("skill")
        if not node_id or not skill:
            raise GraphComposeError(f"节点缺少 id 或 skill: {n!r}")
        if node_id in seen:
            raise GraphComposeError(f"重复节点 id: {node_id}")
        if skill not in candidate_names:
            raise GraphComposeError(
                f"节点 {node_id} 引用越界能力 {skill}（不在候选集）"
            )
        seen.add(node_id)
        inputs = n.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise GraphComposeError(f"节点 {node_id} 的 inputs 必须是对象")
        kwargs: dict[str, Any] = {}
        input_refs: dict[str, str] = {}
        for arg, val in inputs.items():
            resolved, ref = _substitute(val, question)
            if ref is not None:
                input_refs[arg] = f"node:{ref}"
            else:
                kwargs[arg] = resolved
        g.add_node(node_id, skill, kwargs=kwargs, input_refs=input_refs)

    edges_raw = data.get("edges") or []
    if not isinstance(edges_raw, list):
        raise GraphComposeError("edges 必须是数组")
    for e in edges_raw:
        if not isinstance(e, dict):
            raise GraphComposeError(f"边必须是对象: {e!r}")
        dependent = e.get("dependent")
        dependency = e.get("dependency")
        if not dependent or not dependency:
            raise GraphComposeError(f"边缺少 dependent/dependency: {e!r}")
        if dependent not in seen or dependency not in seen:
            raise GraphComposeError(
                f"边引用未知节点: dependent={dependent} dependency={dependency}"
            )
        g.add_edge(dependent, dependency)

    if g.detect_cycle():
        raise GraphComposeError("LLM 产出的 Graph 存在循环依赖")
    return g


_SYSTEM_PROMPT = (
    "你是执行计划编译器。根据用户的请求和下方可用的能力列表，输出一个调用这些能力的"
    "有向无环图（DAG）。规则：\n"
    "1. 只能使用列表中的能力（skill 字段必须是候选名之一）；\n"
    "2. 每个节点有唯一 id、skill、inputs（参数映射）；\n"
    "3. inputs 中可用 '$query' 表示原始问题，'$node.<节点id>' 表示引用上游节点的输出；\n"
    "4. edges 描述依赖：dependent 依赖 dependency（dependency 先执行）；\n"
    "5. 严禁生成任何代码或函数，只组合已有能力；图必须无环。\n"
    "只输出 JSON：{\"nodes\": [{\"id\": \"n1\", \"skill\": \"<名>\", \"inputs\": {\"query\": \"$query\"}}], "
    "\"edges\": [{\"dependent\": \"n2\", \"dependency\": \"n1\"}]}。"
)


def _build_user_prompt(question: str, candidates: list[Any], feedback: str | None = None) -> str:
    lines = [f"用户请求：{question}", "", "可用能力："]
    for s in candidates:
        lines.append(f"- {s.name}: {s.description}")
    if feedback:
        lines.append("")
        lines.append(f"注意（上一轮规划失败，请修正）：{feedback}")
    return "\n".join(lines)


async def compose_execution_graph(
    question: str,
    candidates: list[Any],
    llm: Any,
    feedback: str | None = None,
) -> ExecutionGraph:
    """经 LLM 组合多 Skill DAG。

    :param question: 原始问题。
    :param candidates: 候选 Skill（discover 缩窄后的子集），LLM 只能从中选择。
    :param llm: 决策期 LLM（LangChain 风格；优先 ``with_structured_output``，否则解析 content）。
    :raises GraphComposeError: LLM 未产出可用结构或 IR 校验失败。
    """
    candidate_names = {s.name for s in candidates}
    prompt = _build_user_prompt(question, candidates, feedback=feedback)

    raw = None
    structured = getattr(llm, "with_structured_output", None)
    if structured is not None:
        try:
            resp = await llm.with_structured_output(dict).ainvoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
            raw = resp
        except Exception:  # noqa: BLE001 回退到普通 invoke + JSON 解析
            raw = None
    if raw is None:
        resp = await llm.ainvoke(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        import json

        try:
            raw = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise GraphComposeError(f"LLM 输出非 JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise GraphComposeError("LLM 输出结构非法（非对象）")
    return parse_graph_json(raw, question, candidate_names)


__all__ = [
    "GraphComposeError",
    "compose_execution_graph",
    "parse_graph_json",
]
