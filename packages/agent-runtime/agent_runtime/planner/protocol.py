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

import asyncio
import contextvars
import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.planner.durability import (
    ExecutionNotOwned,
    ExecutionOwnershipStore,
    InMemoryExecutionOwnershipStore,
    reap_stale_executions,
)
from agent_runtime.trajectory.models import TrajectoryStep

StreamEventType = Literal["route", "evidence", "memory", "answer", "error", "status", "replan"]

# 当前执行上下文绑定的 Runtime（在 ``execution()`` 边界内 set，边界外为 None）。
# 供嵌套 Skill 执行器（如 Workflow Skill 内部执行子 Skill）获取 Runtime 并经
# ``delegate`` 受组合治理，避免绕过护栏（架构契约：Skill→Skill 须经 Runtime）。
_runtime_var: contextvars.ContextVar["PlannerRuntime | None"] = contextvars.ContextVar(
    "planner_runtime", default=None
)


def get_current_runtime() -> "PlannerRuntime | None":
    """获取当前执行边界内的 PlannerRuntime（不在 execution() 边界内返回 None）。

    嵌套 Skill 执行器（Workflow / Agent Skill）经此拿到 Runtime，调用 ``delegate``
    执行子 Skill，复用同一执行上下文（预算 / 调用栈 / trace）受治理。
    """
    return _runtime_var.get()


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

    .. deprecated:: 0.2.0
       ``notes`` 承载决策期附加信息，正在迁移至对应 Context 层（PlannerContext/ConversationContext/TaskState/PlanningState/ExecutionIdentity）。
       新代码禁止写入；读取路径暂保留兼容，后续版本将删除。
    """

    mode: Literal["deterministic", "workflow", "graph", "agentic"] = "deterministic"
    route: str = ""
    sub_query: str = ""
    reason: str = ""
    # 显式字段：替代 Plan.notes 迁移（P1 架构债务）
    question: str = ""
    workspace_id: str = "default"
    user_id: str = "default"
    last_snapshot: dict[str, Any] | None = None
    messages: list[Any] = Field(default_factory=list)
    compacted: bool = False
    iterations: int = 0
    mcp_server: str = ""
    mcp_tool: str = ""
    mcp_params: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = ""
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

    # 显式字段：替代 Plan.notes 迁移（P1 架构债务）
    question: str = ""
    previous_execution: dict[str, Any] | None = None  # 上一轮执行快照


@dataclass(frozen=True)
class ExecutionIdentity:
    """执行身份/租户标识：替代 Plan.notes 中的 workspace_id / user_id。

    生命周期：随 ExecutionContext 创建，随 execution 结束销毁。
    用于：trace / audit / authorization / memory namespace / tenant isolation
    """
    execution_id: str
    workspace_id: str = "default"
    user_id: str = "default"


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
    identity: ExecutionIdentity | None = None
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
    # P3-1：逐步明细（skill / args / result / latency / tokens / error），供 Trajectory 持久化
    steps: list[TrajectoryStep] = field(default_factory=list)
    # P5-1：语义循环指纹（skill + 归一化 args），重复指纹拒绝继续（需 enable_loop_fingerprint 开启）
    fingerprints: set[str] = field(default_factory=set)
    loop_fingerprint: bool = False
    # §HA：执行所有权丢失检测（split-brain 的 A 侧）。心跳协程发现租约被新 owner 接管后
    # 置 True，执行循环逐层检查后协作式中止，避免旧 owner 继续产生副作用。
    ownership_lost: bool = False
    # §HA：本次执行持有的 lease owner 标识（供心跳/ownership-loss 检测用）。
    lease_owner: str | None = None

    @property
    def call_depth(self) -> int:
        """当前嵌套深度（调用栈长度）。"""
        return len(self.call_stack)

    def enter_skill(self, name: str, kwargs: dict[str, Any] | None = None) -> None:
        """进入 Skill：步数预算 → 循环检测 → 深度上限 → 语义指纹，超限抛 SkillCompositionError。

        P5-1 语义指纹：对 ``(name, 归一化 kwargs)`` 求指纹，重复指纹（同一 Skill 同入参再次
        调用，如 ``A → B → A'`` 同 args）拒绝继续——比 ``name in call_stack`` 仅查即时重入
        更宽，能拦「绕一圈回来重复调用」的语义循环，又不误伤「不同入参的同名 Skill」。
        """
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
        fp = _fingerprint(name, kwargs or {})
        if self.loop_fingerprint and fp in self.fingerprints:
            raise SkillCompositionError(
                f"语义循环检测：重复调用 {name}（同入参已执行过），拒绝继续"
            )
        self.fingerprints.add(fp)
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

    def record_step(
        self,
        name: str,
        args: dict[str, Any],
        result: Any = None,
        error: str | None = None,
        latency: float = 0.0,
        tokens: int = 0,
    ) -> None:
        """记录一次 Skill 调用明细（P3-1 Trajectory 来源）。

        ``index`` 取当前 ``steps`` 长度（同 execution 内从 0 递增），保证 replay 顺序。
        """
        self.steps.append(
            TrajectoryStep(
                name=name,
                args=args,
                result=result,
                error=error,
                latency=latency,
                tokens=tokens,
                index=len(self.steps),
            )
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
        trajectory_store: Any = None,
        checkpoint_store: Any = None,
        side_effect_store: Any = None,
        enable_loop_fingerprint: bool = False,
        ownership_store: Any = None,
        workspace_id: str = "default",
        user_id: str = "default",
        replica_id: str = "replica",
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
        self.trajectory_store = trajectory_store
        self.checkpoint_store = checkpoint_store
        # §HA（H2）：副作用审计/幂等存储，运行时 delegate 成功后落库，配合 checkpoint
        # 使 B 接管 resume 时可判断哪些 step 已真正落地（effectively-once 证据）。
        self.side_effect_store = side_effect_store
        self.ownership_store: ExecutionOwnershipStore = (
            ownership_store
            if ownership_store is not None
            else InMemoryExecutionOwnershipStore()
        )
        self.enable_loop_fingerprint = enable_loop_fingerprint
        self._workspace_id = workspace_id
        self._user_id = user_id
        # §HA（C2）：副本标识（如 "agent-a"/"agent-b"），参与 owner identity，
        # 避免多容器下 os.getpid() 撞车（容器内主进程常为 PID 1）。
        self._replica_id = replica_id
        # P2-2 计量接线：把 llm 客户端的 usage 回调接到当前执行的 ExecutionContext。
        # 计量源（agent-core FallbackChatModel）→ 聚合器（ExecutionContext.record_usage）
        # 经 contextvars 按 asyncio task 隔离：LLM 调用发生时取当前执行上下文，跨执行不串。
        if llm is not None and hasattr(llm, "set_on_usage"):
            llm.set_on_usage(self._on_llm_usage)
        # 最近一次执行的 ContextManager snapshot（execute_plan 写入，供下一轮组装消费）
        self.last_snapshot: dict[str, Any] | None = None
        # 最近一次执行的 Trajectory 记录（execute_plan 写入，P3-1 持久化后回写）
        self.last_trajectory: Any = None
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
    async def execution(
        self, *, validate_composition: bool = True, execution_id: str | None = None
    ) -> AsyncIterator[None]:
        """单次执行边界：创建 ExecutionContext 并绑定，退出时复位。

        语义（架构审核 P1 修正）：``max_steps`` 是「单次执行累计 Skill 调用数」——
        顺序调用（A 退出后再进 B）与嵌套调用同样消耗预算；``max_skill_depth`` 才
        约束同时嵌套深度。调用方（组合型 Planner 的 execute/arun 入口）须用本 scope
        包裹整次执行：预算不跨执行累计，同执行内顺序/嵌套 Skill 共享同一预算。

        生命周期职责（§7.1 / §11 / §HA）：
        - 进入时若 ``validate_composition`` 且 registry 非空，先跑 ``CompositionValidator``
          静态校验（存在性 / 环 / 权限闭包），组合非法则 fail-fast；
        - 进入时经 ``ownership_store`` acquire 执行所有权（租约），并起心跳续租协程；
          退出时 release，stale 执行可由 ``reap_stale`` 回收（跨进程唤醒见 §20）。
        - ``execution_id`` 可显式注入（resume/HA 接管他人执行时传被恢复执行的 id），
          不传则新建——保证 lease 与 checkpoint 绑定同一 execution_id（§HA 修复合并回归）。
        - §HA split-brain 防护：心跳续租带 owner 校验，租约被新 owner 接管时置
          ``ctx.ownership_lost=True``，执行循环逐层检查后协作式中止，避免旧 owner
          继续产生副作用。
        """
        deadline = (
            time.monotonic() + self.max_duration_seconds
            if self.max_duration_seconds is not None
            else None
        )
        eid = execution_id or uuid.uuid4().hex
        ctx = ExecutionContext(
            execution_id=eid,
            max_steps=self.max_steps, max_depth=self.max_skill_depth, deadline=deadline,
            max_tokens=self.max_tokens, max_cost=self.max_cost,
            loop_fingerprint=self.enable_loop_fingerprint,
            identity=ExecutionIdentity(
                execution_id=eid,
                workspace_id=self._workspace_id,
                user_id=self._user_id,
            ),
        )
        # 组合静态校验（plan 期 fail-fast）：非法组合不进入执行。
        # 仅真实 SkillRegistry 具备 assert_composition_valid；测试替身（_FakeRegistry 等）
        # 不强制实现组合校验，跳过（生产运行时始终为真实注册表）。
        if validate_composition and self.registry is not None:
            validator = getattr(self.registry, "assert_composition_valid", None)
            if validator is not None:
                validator()

        # 执行所有权 / 租约
        # §HA（C2）：owner 用 <replica_id>:<uuid>，跨副本唯一——多容器下
        # os.getpid() 可能同为 1（Docker 主进程），会使 heartbeat fencing 失效。
        owner = f"{self._replica_id}:{uuid.uuid4().hex}"
        lease_ttl = self.max_duration_seconds or 300.0
        acquired = await self.ownership_store.acquire(eid, owner, lease_ttl)
        if not acquired:
            # §HA（C1 fail-closed）：lease 被其他副本持有/未过期，立即拒绝执行，
            # 不得进入 _run_graph_in_place——否则破坏 single-active-owner。
            raise ExecutionNotOwned(
                f"未能获取 execution={eid} 的所有权（lease 被其他副本持有或未过期）"
            )
        ctx.lease_owner = owner

        hb_task: "asyncio.Task | None" = None
        if lease_ttl is not None:
            async def _heartbeat() -> None:
                try:
                    while True:
                        await asyncio.sleep(lease_ttl / 2)
                        ok = await self.ownership_store.heartbeat(eid, lease_ttl, owner=owner)
                        if not ok:
                            # §HA：租约被新 owner 接管/已过期——标记丢失，执行循环将中止
                            ctx.ownership_lost = True
                            return
                except asyncio.CancelledError:
                    return

            hb_task = asyncio.create_task(_heartbeat())

        token = self._ctx_var.set(ctx)
        rt_token = _runtime_var.set(self)
        try:
            yield
        finally:
            if hb_task is not None:
                hb_task.cancel()
                try:
                    await hb_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self.ownership_store.release(eid, owner)
            self._ctx_var.reset(token)
            _runtime_var.reset(rt_token)

    async def reap_stale(self, *, on_stale=None) -> "list[str]":
        """回收 stale 执行（§11 stale execution recovery 生命周期入口）。

        检测租约超时且仍持有的执行，释放所有权并使其 checkpoint 可被 resume 接管。
        跨进程真正唤醒另一副本去 resume 属环境依赖（§20），本方法只完成可单测的
        进程内检测 + 所有权回收。
        """
        return await reap_stale_executions(
            self.ownership_store,
            self.checkpoint_store,
            on_stale=on_stale,
        )

    @asynccontextmanager
    async def skill_guard(self, name: str, kwargs: dict[str, Any] | None = None) -> AsyncIterator[None]:
        """Skill 组合护栏：步数上限 → 循环检测 → 深度上限 → 语义指纹，进入 Skill 前包裹。

        用法（组合型 Planner 编排 Skill 时）：
            async with runtime.execution():
                async with runtime.skill_guard(skill_name, kwargs):
                    result = await runtime.registry.execute(skill_name, **kwargs)

        或经 ``delegate()`` 一步到位（推荐）。护栏状态委托给 ``ExecutionContext``，
        经 contextvars 按 asyncio task 隔离：同 task 链内共享预算（单次执行内累计），
        跨执行（execution 边界）复位。
        """
        ctx = self._ctx_var.get()
        if ctx is None:
            raise SkillCompositionError("skill_guard 须在 execution() 边界内使用")
        ctx.enter_skill(name, kwargs)
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
        async with self.skill_guard(name, kwargs):
            ctx = self._ctx_var.get()
            t0 = time.monotonic()
            tokens_before = ctx.tokens_used if ctx else 0
            try:
                result = await self.registry.execute(name, **kwargs)
            except Exception as exc:
                if ctx is not None:
                    ctx.record_step(
                        name, kwargs, None, str(exc),
                        time.monotonic() - t0, ctx.tokens_used - tokens_before,
                    )
                raise
            if ctx is not None:
                ctx.record_step(
                    name, kwargs, result, None,
                    time.monotonic() - t0, ctx.tokens_used - tokens_before,
                )
            return result


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


def _fingerprint(name: str, kwargs: dict[str, Any]) -> str:
    """P5-1：``(skill, 归一化 args)`` 稳定指纹（sha256 十六进制）。

    归一化：键排序；对不可 JSON 序列化对象回退 ``repr``；长字符串截断避免超大/不稳定
    哈希（可变对象 / 大 payload 先做规范化，符合 roadmap P5-1 备注）。
    """

    def _default(obj: Any) -> str:
        return repr(obj)

    def _trunc(value: Any, limit: int = 512) -> Any:
        if isinstance(value, str) and len(value) > limit:
            return value[:limit] + "...(truncated)"
        return value

    try:
        normalized = json.dumps(
            {"name": name, "args": {k: _trunc(v) for k, v in kwargs.items()}},
            sort_keys=True,
            ensure_ascii=False,
            default=_default,
        )
    except Exception:  # noqa: BLE001 极端情况下回退 repr
        normalized = repr((name, sorted(kwargs.items())))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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

