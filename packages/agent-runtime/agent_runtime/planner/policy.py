"""Policy Validator（Plan-F）：Planner 产出 ExecutionGraph 后，执行前的策略校验。

架构契约：**LLM 负责提出计划，Runtime 负责验证和执行计划**。PolicyValidator 是
Runtime 侧的校验闸门——不修改图，只校验，违规抛 ``PlanViolationError`` 拒绝执行。

校验项：
1. **无环**：ExecutionGraph.detect_cycle（DAG 才可分层并行）；
2. **深度上限**：图的最大依赖链层数 ≤ max_depth；
3. **步数上限**：总节点数 ≤ max_steps；
4. **能力注册**：节点引用的 skill_name 须在 SkillRegistry 已注册；
5. **权限**：skill.permissions 非空时须 ⊆ caller_permissions。

不校验执行级边界（超时 / 熔断 / retry）——那些在 SkillRegistry.execute 洋葱链收敛。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.planner.execution_graph import ExecutionGraph
from agent_runtime.skills.registry import SkillNotFoundError, SkillRegistry


class PlanViolationError(ValueError):
    """执行图策略校验失败：循环 / 深度 / 步数 / 权限 / 未注册能力。"""


class PolicyValidator:
    """执行图策略校验器：校验 ExecutionGraph 是否可安全执行。

    构造时注入 ``SkillRegistry``（用于查 Skill.permissions 与注册状态）。
    ``validate()`` 返回校验通过的图（原样返回，不修改），违规抛 ``PlanViolationError``。
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        graph: ExecutionGraph,
        *,
        max_depth: int = 4,
        max_steps: int = 20,
        max_parallel: int | None = None,
        caller_permissions: frozenset[str] | set[str] | None = None,
    ) -> ExecutionGraph:
        """校验执行图，全部通过则原样返回，任一违规聚合抛 ``PlanViolationError``。"""
        violations: list[str] = []

        # 1. 循环检测（前置：后续深度计算依赖无环）
        if graph.detect_cycle():
            violations.append("执行图存在循环依赖")
            raise PlanViolationError("; ".join(violations))

        # 2. 深度上限
        depth = graph.max_depth()
        if depth > max_depth:
            violations.append(f"图深度 {depth} 超上限 {max_depth}")

        # 3. 步数上限
        steps = graph.step_count()
        if steps > max_steps:
            violations.append(f"节点数 {steps} 超步数上限 {max_steps}")

        # 4. 并行度上限（同层节点数）
        if max_parallel is not None:
            for j, layer in enumerate(graph.topological_layers()):
                if len(layer) > max_parallel:
                    violations.append(f"第 {j} 层并行度 {len(layer)} 超上限 {max_parallel}")

        # 5. 能力注册 + 权限校验
        allowed = frozenset(caller_permissions) if caller_permissions is not None else None
        for node in graph.nodes.values():
            try:
                skill = self._registry.get(node.skill_name)
            except SkillNotFoundError:
                violations.append(
                    f"节点 {node.node_id} 调用未注册能力 {node.skill_name}"
                )
                continue
            if allowed is not None and skill.permissions and not skill.permissions <= allowed:
                violations.append(
                    f"节点 {node.node_id} 调用 {node.skill_name} 需权限 "
                    f"{set(skill.permissions)}，调用方仅持 {set(allowed)}"
                )

        if violations:
            raise PlanViolationError("; ".join(violations))
        return graph

    def validate_or_raise(
        self,
        graph: ExecutionGraph,
        **kwargs: Any,
    ) -> ExecutionGraph:
        """``validate`` 的别名（显式语义，调用方表明期望成功否则抛异常）。"""
        return self.validate(graph, **kwargs)
