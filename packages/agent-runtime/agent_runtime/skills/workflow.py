"""Workflow Skill（完整架构 Phase C）：静态 DAG → 编译为 Workflow Skill 注册 SkillRegistry。

架构契约（docs/complete-agent-runtime-architecture.md §6）：
- Workflow 定义（节点 / 依赖边 / 输入输出 schema）经 ``compile_workflow`` 编译为
  一个 ``Skill(kind=WORKFLOW)``，具备统一的 name / input_schema / output_schema / permissions；
- 注册后，Mode Selector / Planner 可像普通能力一样 discover 并调用它；
- 执行时由 ``WorkflowExecutor`` 把定义还原为 ``ExecutionGraph``，并经统一 Runtime
  （``delegate`` / 组合治理 / 轨迹）执行——拥有 discover / permission / 超时 / 重试 /
  熔断 / tracing / trajectory 等统一运行时能力。

输入映射（节点 ``inputs``）语义与 Dynamic Graph 一致：
- ``"$input.<key>"``：来自 Workflow Skill 被调用时的入参 kwargs；
- ``"$node.<node_id>"``：引用上游节点输出（执行期动态解析）；
- 其他值视为字面量透传。

YAML 文件格式示例（§20 演进落地）：
```yaml
name: "qa_pipeline"
description: "通用问答流水线"
input_schema:
  type: object
  properties:
    question: {type: string}
  required: [question]
nodes:
  - id: "route"
    skill: "route"
    inputs:
      question: "$input.question"
  - id: "search"
    skill: "search"
    inputs:
      query: "$input.question"
  - id: "summarize"
    skill: "summarize"
    inputs:
      text: "$node.search"
edges:
  - dependent: "search"
    dependency: "route"
  - dependent: "summarize"
    dependency: "search"
output_node: "summarize"
permissions: ["read", "search"]
```
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import BaseModel, Field

from agent_runtime.planner.execution_graph import (
    ExecutionGraph,
    _run_graph_in_place,
)
from agent_runtime.planner.protocol import PlannerRuntime, get_current_runtime
from agent_runtime.skills.registry import Skill, SkillKind


class WorkflowNode(BaseModel):
    """工作流节点：一次 Skill 调用（skill 须已在注册表）。"""

    id: str
    skill: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    """依赖边：dependent 依赖 dependency（dependency 先执行）。"""

    dependent: str
    dependency: str


class WorkflowSpec(BaseModel):
    """Workflow 定义：节点 + 依赖边 + 契约。"""

    name: str
    description: str
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge] = Field(default_factory=list)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    # 返回哪个节点的结果作为 Workflow 输出；缺省取最后一个节点。
    output_node: str | None = None
    permissions: frozenset[str] = Field(default_factory=frozenset)
    metadata: dict[str, Any] = Field(default_factory=dict)


_INPUT_REF = "$input."


def _resolve_input(value: Any, call_kwargs: dict[str, Any]) -> tuple[Any, str | None]:
    """解析单个输入值：``$input.<k>`` → 调用入参；``$node.<id>`` → 执行期 ref；否则字面量。"""
    if isinstance(value, str):
        if value.startswith(_INPUT_REF):
            key = value[len(_INPUT_REF) :]
            return call_kwargs.get(key), None
        if value.startswith("$node."):
            return value, value[len("$node.") :]
    return value, None


class WorkflowExecutor:
    """Workflow Skill 执行器：把 ``WorkflowSpec`` 还原为 ExecutionGraph 并经统一 Runtime 执行。

    边界处理（doc §7 Skill→Skill 须经 Runtime）：
    - 若已处于某个 ``execution()`` 边界内（如经 ``execute_plan`` 单 route delegate 调用），
      直接用 ``_run_graph_in_place`` 复用同一执行上下文（预算 / 调用栈 / trace 连续累计）；
    - 否则（独立调用）创建新的 ``PlannerRuntime`` + 边界，保证组合治理与轨迹可用。
    """

    def __init__(self, spec: WorkflowSpec, registry: Any | None = None) -> None:
        self._spec = spec
        self._registry = registry

    def _build_graph(self, call_kwargs: dict[str, Any]) -> ExecutionGraph:
        g = ExecutionGraph()
        for n in self._spec.nodes:
            node_kwargs: dict[str, Any] = {}
            input_refs: dict[str, str] = {}
            for arg, val in n.inputs.items():
                resolved, ref = _resolve_input(val, call_kwargs)
                if ref is not None:
                    input_refs[arg] = f"node:{ref}"
                else:
                    node_kwargs[arg] = resolved
            g.add_node(n.id, n.skill, kwargs=node_kwargs, input_refs=input_refs)
        for e in self._spec.edges:
            g.add_edge(e.dependent, e.dependency)
        return g

    async def execute(self, **kwargs: Any) -> Any:
        runtime = get_current_runtime()
        if runtime is None:
            if self._registry is None:
                raise RuntimeError("Workflow 独立执行需要 registry 或处于 execution 边界内")
            runtime = PlannerRuntime(registry=self._registry)
            async with runtime.execution():
                return await self._run(runtime, kwargs)
        return await self._run(runtime, kwargs)

    async def _run(self, runtime: PlannerRuntime, kwargs: dict[str, Any]) -> Any:
        graph = self._build_graph(kwargs)
        results: dict[str, Any] = {}
        errors: list[str] = []
        async for event in _run_graph_in_place(graph, runtime):
            if event.type == "evidence":
                results[event.payload["node"]] = event.payload["result"]
            elif event.type == "error":
                errors.append(
                    f"{event.payload.get('node')}: {event.payload.get('error')}"
                )
        if errors:
            raise RuntimeError("; ".join(errors))
        out_node = self._spec.output_node or (
            self._spec.nodes[-1].id if self._spec.nodes else None
        )
        if out_node is None:
            return results
        return results.get(out_node)


def compile_workflow(spec: "WorkflowSpec | dict[str, Any]", *, registry: Any | None = None) -> Skill:
    """把 Workflow 定义编译为 Workflow Skill（kind=WORKFLOW）。

    :param spec: ``WorkflowSpec`` 或等价 dict。
    :param registry: 可选注册表，供 Workflow 独立执行（不经过统一 Runtime 边界时）回溯子能力。
    :return: 可注册到 ``SkillRegistry`` 的 ``Skill``（含 input/output schema 与权限声明）。
    """
    if not isinstance(spec, WorkflowSpec):
        spec = WorkflowSpec(**spec)
    executor = WorkflowExecutor(spec, registry=registry)
    return Skill(
        name=spec.name,
        description=spec.description,
        kind=SkillKind.WORKFLOW,
        executor=executor.execute,
        input_schema=spec.input_schema,
        output_schema=spec.output_schema,
        permissions=frozenset(spec.permissions),
        metadata={**spec.metadata, "kind": "workflow"},
    )


def load_workflow_yaml(path: str | pathlib.Path, *, registry: Any | None = None) -> Skill:
    """从 YAML 文件加载并编译为 Workflow Skill。

    :param path: .yaml/.yml 文件路径。
    :param registry: 可选注册表，传给 ``compile_workflow``。
    :return: 可直接注册到 ``SkillRegistry`` 的 ``Skill``。
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")
    content = p.read_text(encoding="utf-8")
    spec_dict = yaml.safe_load(content)
    return compile_workflow(spec_dict, registry=registry)


def discover_workflows(
    directory: str | pathlib.Path,
    *,
    registry: Any | None = None,
    pattern: str = "*.y*ml",
) -> list[Skill]:
    """递归扫描目录，加载所有匹配的 Workflow YAML 文件。

    :param directory: 扫描根目录（如 ``workflows/``）。
    :param registry: 可选注册表，传给 ``compile_workflow``。
    :param pattern: glob 模式（默认 ``*.y*ml`` 兼容 .yaml/.yml）。
    :return: 编译后的 ``Skill`` 列表，按文件名排序以保证确定性。
    """
    root = pathlib.Path(directory)
    if not root.exists() or not root.is_dir():
        return []
    skills: list[Skill] = []
    for file in sorted(root.rglob(pattern)):
        try:
            skills.append(load_workflow_yaml(file, registry=registry))
        except Exception as e:
            raise RuntimeError(f"Failed to load workflow {file}: {e}") from e
    return skills


__all__ = [
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowExecutor",
    "compile_workflow",
    "load_workflow_yaml",
    "discover_workflows",
]
