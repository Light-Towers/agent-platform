"""Mode Selector（完整架构 Phase A）：轻量级「选择执行范式」，不生成完整 DAG。

架构契约（docs/complete-agent-runtime-architecture.md §3.2）：
- 准入（Admission）成功后，由 Mode Selector 判断执行范式；
- Mode Selector **只选择** Planner/Execution Mode，不生成完整 DAG；
- 选择优先级（doc §3.2）：
  1. 明确的静态规则优先（``force_mode`` override，对应 ``PLANNER=`` 配置，用于调试/灰度）；
  2. 已注册 Workflow Skill 优先复用（稳定业务流程不应重新让 LLM 规划）；
  3. 可组合且边界明确的问题进入 Dynamic Graph（多候选能力）；
  4. 高不确定性、开放式探索任务才进入 Agentic（默认不进入，避免一切问题都交 Agent loop）。

``ModeSelector`` 保持中立：只依赖 ``SkillRegistry.discover`` 与可选的 ``classifier``
（LLM 决策函数，由宿主注入）；本身不依赖具体 Planner 实现，也不直接执行能力。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from agent_runtime.planner.protocol import PlannerContext

if TYPE_CHECKING:
    from agent_runtime.skills.registry import SkillRegistry

# 可选 LLM 分类器签名：给定问题与 registry，异步返回 ExecutionMode 字符串。
ModeClassifier = Callable[[str, "SkillRegistry"], Awaitable[str]]


class ExecutionMode(StrEnum):
    """四种执行范式（与 ``Plan.mode`` 对齐）。"""

    DETERMINISTIC = "deterministic"
    WORKFLOW = "workflow"
    GRAPH = "graph"
    AGENTIC = "agentic"


@dataclass
class ModeDecision:
    """Mode Selector 的输出：选中的执行范式 + 理由 + 可选命中 Workflow。

    ``workflow_skill``：当 ``mode == WORKFLOW`` 时，命中的已注册 Workflow Skill 名；
    execute 阶段经 ``delegate(workflow_skill)`` 走统一 Runtime。
    """

    mode: ExecutionMode
    reason: str
    workflow_skill: str | None = None
    confidence: float = 1.0


class ModeSelector:
    """自动选择执行范式：force override → Workflow 复用 → 可选 LLM → 启发式。

    默认启发式偏向「确定性 / 可组合」，**不会**把开放式任务默认送进 Agentic——
    仅当 ``agentic_enabled`` 且 ``classifier`` 显式返回 agentic 时才进入
    （doc §17：不要所有任务都用 Agentic）。
    """

    def __init__(
        self,
        *,
        force_mode: str | None = None,
        classifier: "ModeClassifier | None" = None,
        agentic_enabled: bool = False,
        workflow_kind: str = "workflow",
        workflow_min_score: int = 2,
        graph_min_relevant: int = 2,
        top_k: int = 10,
    ) -> None:
        self._force_mode = ExecutionMode(force_mode) if force_mode else None
        self._classifier = classifier
        self._agentic_enabled = agentic_enabled
        self._workflow_kind = workflow_kind
        # 关键词匹配是粗粒度启发式（单字重叠会有噪声），workflow 复用要求更强的匹配信号，
        # 避免「任务」二字误命中「财务」之类；生产路径应注入 LLM classifier。
        self._workflow_min_score = workflow_min_score
        self._graph_min_relevant = graph_min_relevant
        self._top_k = top_k

    async def select(self, ctx: PlannerContext, registry: "SkillRegistry") -> ModeDecision:
        """根据问题 + 可用能力选择执行范式。

        :param ctx: 决策输入（含 question / workspace / user / messages 等）。
        :param registry: 能力注册表，用于 discover 候选 Workflow / 普通 Skill。
        :return: ``ModeDecision``（mode + reason + 可选 workflow_skill）。
        """
        query = ctx.question

        # 1. 强制 override（PLANNER= 配置 / 调试灰度）
        if self._force_mode is not None:
            return ModeDecision(
                self._force_mode,
                reason="forced by PLANNER override",
            )

        # 2. 已注册 Workflow Skill 优先复用
        wf = registry.discover(
            query, top_k=1, metadata_filter={"kind": self._workflow_kind}
        )
        if wf and self._score(query, wf[0]) >= self._workflow_min_score:
            return ModeDecision(
                ExecutionMode.WORKFLOW,
                reason=f"复用已注册 Workflow Skill {wf[0].name}",
                workflow_skill=wf[0].name,
                confidence=1.0,
            )

        # 3. 可选 LLM 分类器（宿主注入；未注入则走启发式）
        if self._classifier is not None:
            proposed = ExecutionMode(await self._classifier(query, registry))
            if proposed == ExecutionMode.AGENTIC and not self._agentic_enabled:
                proposed = ExecutionMode.GRAPH
            return ModeDecision(
                proposed, reason="llm classifier", confidence=0.9
            )

        # 4. 启发式：deterministic vs graph（默认不进 agentic）
        # 信号是「不同相关能力的数量」：>= graph_min_relevant 个独立相关能力 → 可组合走 graph；
        # 否则视为单一明确能力走 deterministic（doc §2：简单问答/固定单能力走 deterministic）。
        candidates = registry.discover(query, top_k=self._top_k)
        if not candidates:
            return ModeDecision(
                ExecutionMode.DETERMINISTIC,
                reason="无候选能力，回退 deterministic/direct",
                confidence=0.6,
            )
        relevant = [c for c in candidates if self._relevant(c, query)]
        if len(relevant) >= self._graph_min_relevant:
            return ModeDecision(
                ExecutionMode.GRAPH,
                reason="多候选能力可组合，走 Dynamic Graph",
                confidence=0.7,
            )
        return ModeDecision(
            ExecutionMode.DETERMINISTIC,
            reason="单一明确能力，走 deterministic",
            confidence=0.8,
        )

    @staticmethod
    def _score(query: str, skill: Any) -> int:
        """复用 registry 的关键词打分（discover 已按此排序）；这里取单 skill 分。"""
        from agent_runtime.skills.registry import SkillRegistry as _R

        return _R._score(query, skill)

    @classmethod
    def _relevant(cls, skill: Any, query: str) -> bool:
        """是否命中关键词（score > 0）。"""
        return cls._score(query, skill) > 0


__all__ = ["ExecutionMode", "ModeDecision", "ModeSelector"]
