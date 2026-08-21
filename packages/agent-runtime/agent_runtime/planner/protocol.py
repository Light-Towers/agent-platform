"""Planner 协议（Plan-F Phase 2）：决策 plan() + 编排 execute()。

契约 P1：``plan(ctx) -> Plan``（决策）+ ``execute(plan, runtime) -> AsyncIterator[StreamEvent]``（执行）。

- 决策（plan）只回答「本次走哪条能力链路」，不持有执行语义；
- 执行（execute）按 Plan 编排能力调用，retry/超时/熔断等执行边界由 Runtime
  （``SkillRegistry.execute`` 的统一边界）承载；
- 事件（StreamEvent）与 SSE 出口事件同构（type + payload），Phase 3 切换出口时可直传。

组合治理（Phase 3）：PlannerRuntime 承载 ``max_skill_depth`` / ``max_steps`` 与
``skill_guard``（步数上限 / 循环检测 / 深度上限），约束「Agent 动态组合 Skill」的
agentic 路径——deterministic 静态 DAG 天然无环，无需也不使用该护栏（不过度设计）。

实现可放在任意侧（app=deterministic / 联邦=agentic），协议保持中立。
"""

from __future__ import annotations

import contextvars
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StreamEventType = Literal["route", "evidence", "memory", "answer", "error", "status", "replan"]


class StreamEvent(BaseModel):
    """统一流式事件：type + payload。

    与现有 SSE 出口事件（``{"type": ..., ...}``）同构，Phase 3 直接展开 payload 即可直传。
    """

    type: StreamEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    """一次决策结果：执行模式 + 能力选择 + 可选执行图。

    ``mode``（Plan-F 执行链打通）：标识本次执行的路径——

    - ``deterministic``：单 route 调用（现有 DeterministicPlanner，route 必填）；
    - ``graph``：多 Skill 组合计划，``graph`` 携带 ExecutionGraph，经 PolicyValidator +
      execute_graph 执行（GraphPlanner）；
    - ``agentic``：LLM 自主 function-calling（AgenticPlanner，不经 ExecutionGraph）。

    ``graph`` 类型为 ``Any`` 以避免 protocol ↔ execution_graph 循环导入，实际为
    ``ExecutionGraph | None``。``mode="graph"`` 时 ``graph`` 必须非空。

    ``notes`` 承载决策期附加信息（脱敏后问题、workspace_id、记忆召回、重试迭代等），
    供 execute 阶段消费；是 Plan 的扩展位，不新增字段即保持协议稳定。
    """

    mode: Literal["deterministic", "graph", "agentic"] = "deterministic"
    route: str = ""
    sub_query: str = ""
    reason: str = ""
    notes: dict[str, Any] = Field(default_factory=dict)
    graph: Any = None


class PlannerContext(BaseModel):
    """决策输入：问题 + 会话上下文。

    ``messages`` 为宽松列表（兼容 LangChain BaseMessage / dict / tuple 等形态），
    由具体 Planner 实现自行解析；``llm`` 为决策期 LLM（路由/压缩/抽取共用）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str
    workspace_id: str = "default"
    user_id: str = "default"
    messages: list[Any] = Field(default_factory=list)
    llm: Any = None
    # WS-2：上一轮执行的结构化快照（task/execution 层），由 app 层从 thread
    # 持久化读出并注入；Planner 在 prompt 组装时结构化消费（不进对话历史存储）。
    last_snapshot: dict[str, Any] | None = None

    # MCP 路由参数（route=mcp 时透传，可选；与 app/agent/state.py AgentState 对应字段一致）
    mcp_server: str = ""
    mcp_tool: str = ""
    mcp_params: dict[str, Any] = Field(default_factory=dict)


class SkillCompositionError(RuntimeError):
    """Skill 组合治理违规：步数超限 / 循环调用 / 嵌套过深（agentic 组合路径）。"""


class PlanningFeedback(StrEnum):
    """Planner 重规划反馈原因：与 Skill 执行异常严格分离。

    语义边界（架构契约）：
    - Skill 执行异常（timeout / circuit / tool unavailable）→ Skill Runtime 处理（retry / fallback）；
    - PlanningFeedback（证据不足 / 路由不匹配）→ Planner 处理（re-plan）。
    不得将 PlanningFeedback 下沉为 SkillRuntime retry，反之亦然。
    """

    EVIDENCE_EMPTY = "evidence_empty"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    ROUTE_MISMATCH = "route_mismatch"
    NEED_MORE_INFORMATION = "need_more_information"
    TOOL_RESULT_SUGGESTS_REPLAN = "tool_result_suggests_replan"


@dataclass
class ExecutionContext:
    """单次 Planner execution 的执行上下文（预算 + 调用栈 + 元数据）。

    架构契约：绑定一次 execution（由 ``PlannerRuntime.execution`` 入口创建），所有嵌套
    Skill 共享。经 ``PlannerRuntime`` 的 ``contextvars`` 按 asyncio task 隔离——异 session
    并发互不干扰，同 task 链内共享同一预算。

    预算语义（与 ``PlannerRuntime.max_steps`` / ``max_skill_depth`` 对齐）：
    - ``step_count``：累计 Skill 调用数（只增不减，顺序 + 嵌套共享）；
    - ``call_stack``：当前嵌套调用栈（enter append / exit pop），``call_depth = len(call_stack)``。

    P2-1 计量聚合（tokens / cost）：
    - ``tokens_used`` / ``cost_used``：单次执行内累计 token 数与费用；
    - ``max_tokens`` / ``max_cost``：可选上限，超限抛 ``SkillCompositionError``；
    - 计量源在 ``agent-core`` llm client 层（P2-2），本类只做聚合器 + 闸门。
    """

    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    step_count: int = 0
    call_stack: list[str] = field(default_factory=list)
    max_steps: int = 20
    max_depth: int = 4
    deadline: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # P2-1：tokens / cost 聚合（计量点由 agent-core llm client 层提供）
    tokens_used: int = 0
    cost_used: float = 0.0
    max_tokens: int | None = None
    max_cost: float | None = None

    @property
    def call_depth(self) -> int:
        """当前嵌套深度（调用栈长度）。"""
        return len(self.call_stack)

    def enter_skill(self, name: str) -> None:
        """进入 Skill：步数预算 → 循环检测 → 深度上限，超限抛 SkillCompositionError。"""
        if self.step_count >= self.max_steps:
            raise SkillCompositionError(
                f"Skill 组合步数超上限（max_steps={self.max_steps}）"
            )
        if name in self.call_stack:
            raise SkillCompositionError(
                f"Skill 循环调用检测: {' -> '.join([*self.call_stack, name])}"
            )
        if len(self.call_stack) >= self.max_depth:
            raise SkillCompositionError(
                f"Skill 嵌套深度超上限（max_depth={self.max_depth}）"
            )
        self.step_count += 1
        self.call_stack.append(name)

    def exit_skill(self) -> None:
        """退出 Skill：仅弹出调用栈，步数预算不回退（累计计数）。"""
        if self.call_stack:
            self.call_stack.pop()

    def record_usage(self, tokens: int = 0, cost: float = 0.0) -> None:
        """记录本次执行的 token / 费用消耗（P2-1 聚合器）。

        累计到 ``tokens_used`` / ``cost_used``；若设置了 ``max_tokens`` / ``max_cost``
        上限且累计值超限，抛 ``SkillCompositionError``（与步数/深度/循环护栏同级）。

        调用方（Planner / agent-core llm client）在每次 LLM 调用后传入本次 usage，
        本方法只做聚合 + 闸门，不关心计量来源。
        """
        self.tokens_used += tokens
        self.cost_used += cost
        if self.max_tokens is not None and self.tokens_used > self.max_tokens:
            raise SkillCompositionError(
                f"tokens 用量超上限（used={self.tokens_used}, max={self.max_tokens}）"
            )
        if self.max_cost is not None and self.cost_used > self.max_cost:
            raise SkillCompositionError(
                f"费用超上限（used={self.cost_used:.4f}, max={self.max_cost:.4f}）"
            )


class PlannerRuntime:
    """执行期依赖句柄：能力注册表必填；llm/mcp_manager/pool 按需注入。

    组合治理（Phase 3）：``max_skill_depth`` / ``max_steps`` 限定「Agent 动态组合 Skill」
    的资源边界；``skill_guard(name)`` 是组合型 Planner（agentic）编排 Skill 时须包裹的
    护栏——步数超限 / 循环调用（同名 Skill 重复入栈）/ 嵌套过深时抛 ``SkillCompositionError``。

    由调用方（app lifespan / eval）装配，注入一次、贯穿会话（单例可复用）。

    并发模型（架构审核 P0 落地）：执行期可变状态（步数/调用栈）经 ``contextvars`` 按
    **执行上下文**（asyncio task）隔离——异 session 并发互不干扰；同 session 串行
    （同一 task 链）共享同一护栏预算。单例注入 + 请求隔离，不再出现「一次执行的预算
    被并发请求耗尽」的跨请求污染。

    ``max_skill_depth`` / ``max_steps`` 为不可变配置（注入一次、贯穿会话）。
    """

    def __init__(
        self,
        registry,
        llm: Any = None,
        mcp_manager: Any = None,
        pool: Any = None,
        *,
        max_skill_depth: int = 4,
        max_steps: int = 20,
        max_duration_seconds: float | None = None,
        max_tokens: int | None = None,
        max_cost: float | None = None,
    ):
        self.registry = registry
        self.llm = llm
        self.mcp_manager = mcp_manager
        self.pool = pool
        self.max_skill_depth = max_skill_depth
        self.max_steps = max_steps
        self.max_duration_seconds = max_duration_seconds
        self.max_tokens = max_tokens
        self.max_cost = max_cost
        # P2-2 计量接线：把 llm 客户端的 usage 回调接到当前执行的 ExecutionContext。
        # 计量源（agent-core FallbackChatModel）→ 聚合器（ExecutionContext.record_usage）
        # 经 contextvars 按 asyncio task 隔离：LLM 调用发生时取当前执行上下文，跨执行不串。
        if llm is not None and hasattr(llm, "set_on_usage"):
            llm.set_on_usage(self._on_llm_usage)
        # 最近一次执行的 ContextManager snapshot（execute_plan 写入，供下一轮组装消费）
        self.last_snapshot: dict[str, Any] | None = None
        # 执行期上下文（per-request，经 ContextVar 隔离）：execution() 入口创建
        # ExecutionContext 并 set，同 task 链内共享，跨 task 互不干扰。
        self._ctx_var: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
            "planner_exec_ctx", default=None
        )

    @property
    def context(self) -> ExecutionContext | None:
        """当前执行上下文（``execution()`` 边界内有效，边界外为 None）。"""
        return self._ctx_var.get()

    def _on_llm_usage(self, tokens: int, cost: float) -> None:
        """P2-2 计量回调：LLM 客户端每次调用后上报 usage → 当前 ExecutionContext 聚合。

        LLM 调用发生在 ``execution()`` 边界内时，取当前上下文计入预算；边界外
        （如 deterministic 静态路径不经 runtime 护栏）回调静默丢弃，不污染跨执行预算。
        """
        ctx = self._ctx_var.get()
        if ctx is not None:
            ctx.record_usage(tokens, cost)

    @property
    def _steps(self) -> int:
        """当前执行上下文的步数计数（兼容既有测试/调试读取）。"""
        ctx = self._ctx_var.get()
        return ctx.step_count if ctx else 0

    @property
    def _call_stack(self) -> list[str]:
        """当前执行上下文的 Skill 调用栈（兼容既有测试/调试读取）。"""
        ctx = self._ctx_var.get()
        return ctx.call_stack if ctx else []

    @asynccontextmanager
    async def execution(self) -> AsyncIterator[None]:
        """单次执行边界：创建 ExecutionContext 并绑定，退出时复位。

        语义（架构审核 P1 修正）：``max_steps`` 是「单次执行累计 Skill 调用数」——
        顺序调用（A 退出后再进 B）与嵌套调用同样消耗预算；``max_skill_depth`` 才
        约束同时嵌套深度。调用方（组合型 Planner 的 execute/arun 入口）须用本 scope
        包裹整次执行：预算不跨执行累计，同执行内顺序/嵌套 Skill 共享同一预算。
        """
        deadline = (
            time.monotonic() + self.max_duration_seconds
            if self.max_duration_seconds is not None
            else None
        )
        ctx = ExecutionContext(
            max_steps=self.max_steps, max_depth=self.max_skill_depth, deadline=deadline,
            max_tokens=self.max_tokens, max_cost=self.max_cost,
        )
        token = self._ctx_var.set(ctx)
        try:
            yield
        finally:
            self._ctx_var.reset(token)

    @asynccontextmanager
    async def skill_guard(self, name: str) -> AsyncIterator[None]:
        """Skill 组合护栏：步数上限 → 循环检测 → 深度上限，进入 Skill 前包裹。

        用法（组合型 Planner 编排 Skill 时）：
            async with runtime.execution():
                async with runtime.skill_guard(skill_name):
                    result = await runtime.registry.execute(skill_name, **kwargs)

        或经 ``delegate()`` 一步到位（推荐）。护栏状态委托给 ``ExecutionContext``，
        经 contextvars 按 asyncio task 隔离：同 task 链内共享预算（单次执行内累计），
        跨执行（execution 边界）复位。
        """
        ctx = self._ctx_var.get()
        if ctx is None:
            raise SkillCompositionError("skill_guard 须在 execution() 边界内使用")
        ctx.enter_skill(name)
        try:
            yield
        finally:
            ctx.exit_skill()

    async def delegate(self, name: str, **kwargs: Any) -> Any:
        """Skill 委派 API：经 ``skill_guard`` 包裹 ``registry.execute``，计入组合预算。

        架构契约（Plan-F Skill Delegation）：Skill → Skill 组合须经此方法，而非直接调
        ``registry.execute``——确保嵌套调用受步数 / 深度 / 循环护栏治理。Workflow Skill
        内部调其他 Skill 时同样须走 ``delegate``，避免绕过护栏（架构审核 P2：此前
        ``general_qa`` 内部直接调 ``registry.execute`` 不计入预算，现已修正）。

        边界回退：不在 ``execution()`` 边界内时（如 deterministic 静态 DAG 路径——天然
        无环、不使用组合护栏）直接执行不护栏，向后兼容。
        """
        if self._ctx_var.get() is None:
            return await self.registry.execute(name, **kwargs)
        async with self.skill_guard(name):
            return await self.registry.execute(name, **kwargs)


class Planner(ABC):
    """Planner 协议：决策 + 编排执行。

    实现方约定：
    - ``kind`` 标识实现类型（deterministic / agentic / ...），用于注册与 PLANNER env 选择；
    - ``plan()`` 必须无副作用、可复现（LLM 路由失败须回退确定性启发式）；
    - ``execute()`` 是 async generator，至少产出 route 事件与 answer 事件。
    """

    kind: str = "abstract"

    @abstractmethod
    async def plan(self, ctx: PlannerContext) -> Plan:
        """决策：给定会话上下文，返回本次执行的 Plan。"""

    @abstractmethod
    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """编排执行：按 Plan 依次调用能力、合成答案，产出统一流式事件。

        ``ctx`` 为可选执行上下文（预算 + 调用栈 + 元数据），由调用方在 execution 入口
        创建并传入，所有嵌套 Skill 共享同一预算。未传入时由 Runtime 内部护栏
        （``skill_guard``）承载组合治理，向后兼容。
        """


def serialize_stream_event(event: StreamEvent) -> dict | None:
    """StreamEvent（Planner 协议）→ 出口事件 dict（与现有 SSE 事件同构，客户端无感）。

    app（SSE）/ 联邦（WS）共用此单一映射，避免双轨出口 schema 漂移（Plan-F WS 出口统一）。
    返回 None 表示忽略该事件（协议未定义的 type）。
    """
    if event.type == "route":
        return {
            "type": "route",
            "capability": event.payload.get("capability"),
            "reason": event.payload.get("reason"),
        }
    if event.type == "evidence":
        return {
            "type": "evidence",
            "node": event.payload.get("node"),
            "count": event.payload.get("count", 0),
            "preview": event.payload.get("preview", ""),
        }
    if event.type == "memory":
        return {"type": "memory", "notes": event.payload.get("notes", [])}
    if event.type == "status":
        return {"type": "status", **event.payload}
    if event.type == "replan":
        return {
            "type": "replan",
            "iteration": event.payload.get("iteration", 0),
            "from_route": event.payload.get("from_route"),
            "to_route": event.payload.get("to_route"),
            "reason": event.payload.get("reason", "evidence_insufficient"),
        }
    if event.type == "answer":
        return {"type": "answer", "text": event.payload.get("text", "")}
    if event.type == "error":
        return {"type": "error", **event.payload}
    return None

