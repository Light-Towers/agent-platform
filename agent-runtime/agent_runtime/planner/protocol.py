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
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StreamEventType = Literal["route", "evidence", "memory", "answer", "error", "status"]


class StreamEvent(BaseModel):
    """统一流式事件：type + payload。

    与现有 SSE 出口事件（``{"type": ..., ...}``）同构，Phase 3 直接展开 payload 即可直传。
    """

    type: StreamEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    """一次决策结果：选中能力 + 子查询 + 理由 + 附加上下文。

    ``notes`` 承载决策期附加信息（脱敏后问题、workspace_id、记忆召回、重试迭代等），
    供 execute 阶段消费；是 Plan 的扩展位，不新增字段即保持协议稳定。
    """

    route: str
    sub_query: str = ""
    reason: str = ""
    notes: dict[str, Any] = Field(default_factory=dict)


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

    # MCP 路由参数（route=mcp 时透传，可选；与 app/agent/state.py AgentState 对应字段一致）
    mcp_server: str = ""
    mcp_tool: str = ""
    mcp_params: dict[str, Any] = Field(default_factory=dict)


class SkillCompositionError(RuntimeError):
    """Skill 组合治理违规：步数超限 / 循环调用 / 嵌套过深（agentic 组合路径）。"""


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
    ):
        self.registry = registry
        self.llm = llm
        self.mcp_manager = mcp_manager
        self.pool = pool
        self.max_skill_depth = max_skill_depth
        self.max_steps = max_steps
        # 执行期可变状态（per-request，经 ContextVar 隔离；default 为共享只读初始值）
        self._steps_var: contextvars.ContextVar[int] = contextvars.ContextVar(
            "planner_steps", default=0
        )
        self._call_stack_var: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
            "planner_call_stack", default=[]
        )

    @property
    def _steps(self) -> int:
        """当前执行上下文的步数计数（兼容既有测试/调试读取）。"""
        return self._steps_var.get()

    @property
    def _call_stack(self) -> list[str]:
        """当前执行上下文的 Skill 调用栈（兼容既有测试/调试读取）。"""
        return self._call_stack_var.get()

    @asynccontextmanager
    async def skill_guard(self, name: str) -> AsyncIterator[None]:
        """Skill 组合护栏：步数上限 → 循环检测 → 深度上限，进入 Skill 前包裹。

        用法（组合型 Planner 编排 Skill 时）：
            async with runtime.skill_guard(skill_name):
                result = await runtime.registry.execute(skill_name, **kwargs)

        护栏状态 per-request：上下文退出即复位（预算不跨执行累计），同 task 链内
        嵌套调用共享预算（单次执行内累计）。
        """
        steps = self._steps_var.get() + 1
        if steps > self.max_steps:
            raise SkillCompositionError(f"Skill 组合步数超上限（max_steps={self.max_steps}）")
        stack = self._call_stack_var.get()
        if name in stack:
            raise SkillCompositionError(
                f"Skill 循环调用检测: {' -> '.join([*stack, name])}"
            )
        if len(stack) >= self.max_skill_depth:
            raise SkillCompositionError(
                f"Skill 嵌套深度超上限（max_skill_depth={self.max_skill_depth}）"
            )
        # 每次 set 新值（list 用新拷贝），不修改共享 default，避免跨 task 污染
        self._steps_var.set(steps)
        self._call_stack_var.set([*stack, name])
        try:
            yield
        finally:
            self._steps_var.set(steps - 1)
            self._call_stack_var.set(stack)


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
    async def execute(self, plan: Plan, runtime: PlannerRuntime) -> AsyncIterator[StreamEvent]:
        """编排执行：按 Plan 依次调用能力、合成答案，产出统一流式事件。"""


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
    if event.type == "answer":
        return {"type": "answer", "text": event.payload.get("text", "")}
    if event.type == "error":
        return {"type": "error", **event.payload}
    return None

