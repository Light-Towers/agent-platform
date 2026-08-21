"""Skill → Skill 一等公民组合模型（§7.1 / 架构文档「Skill → Skill」目标）。

组合应通过 Runtime/Registry（``runtime.delegate``）进行，并由运行时 ``skill_guard``
（max_depth / max_steps / cycle）兜底。本模块提供**计划期静态校验**，把组合治理前移：
在 plan / 注册阶段即可发现「引用不存在的能力」「组合成环」「权限未闭合」等错误，
而非等到运行时 skill_guard 才暴露。

声明方式：``Skill.sub_skills`` 列出本能力直接组合的下层能力名。
"""

from __future__ import annotations

from agent_runtime.skills.registry import SkillRegistry


class CompositionError(ValueError):
    """组合模型校验失败（存在性 / 环 / 权限闭包）。"""


class CompositionValidator:
    """静态校验注册表的 Skill 组合图。

    检查项：
    1. 存在性——``sub_skills`` 引用的能力必须已注册；
    2. 权限闭包——若 A 组合 B，则 B 所需权限必须是 A 权限的超集
       （执行 A 时 Runtime 以 A 的上下文委派 B，A 须持有 B 所需全部权限）；
    3. 无环——组合图不得出现环（否则运行时 skill_guard 也会拦截，但静态期更早暴露）。
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def validate(self) -> "list[str]":
        violations: list[str] = []
        skills = {s.name: s for s in self._registry.list()}
        graph: dict[str, list[str]] = {}

        for name, skill in skills.items():
            subs = list(skill.sub_skills)
            graph[name] = subs
            for sub in subs:
                if sub not in skills:
                    violations.append(
                        f"skill '{name}' 组合了未注册能力 '{sub}'"
                    )
                    continue
                missing = skills[sub].permissions - skill.permissions
                if missing:
                    violations.append(
                        f"skill '{name}' 组合 '{sub}' 但缺少其所需权限 {sorted(missing)}"
                    )

        # 环检测（DFS 三色）
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in graph}

        def _dfs(node: str, stack: list[str]) -> None:
            color[node] = GRAY
            for nxt in graph.get(node, []):
                if nxt not in color:
                    continue  # 不存在的能力已在上面报过
                if color[nxt] == GRAY:
                    violations.append(
                        "组合成环: " + " -> ".join(stack + [nxt])
                    )
                elif color[nxt] == WHITE:
                    _dfs(nxt, stack + [nxt])
            color[node] = BLACK

        for n in list(graph):
            if color[n] == WHITE:
                _dfs(n, [n])

        return violations

    def assert_valid(self) -> None:
        violations = self.validate()
        if violations:
            raise CompositionError("; ".join(violations))
