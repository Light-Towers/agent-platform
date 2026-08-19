"""Planner 协议（Plan-F Phase 2）：决策 plan() + 编排 execute()。

契约 P1：``plan(ctx) -> Plan``（决策）+ ``execute(plan, runtime) -> AsyncIterator[StreamEvent]``（执行）。

- 决策（plan）只回答「本次走哪条能力链路」，不持有执行语义；
- 执行（execute）按 Plan 编排能力调用，retry/超时/熔断等执行边界由 Runtime
  （``CapabilityRegistry.execute`` 的统一边界）承载；
- 事件（StreamEvent）与 SSE 出口事件同构（type + payload），Phase 3 切换出口时可直传。

实现可放在任意侧（app=deterministic / 联邦=agentic），协议保持中立。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
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


class PlannerRuntime:
    """执行期依赖句柄：能力注册表必填；llm/mcp_manager/pool 按需注入。

    由调用方（app lifespan / eval）装配，注入一次、贯穿会话。
    """

    def __init__(self, registry, llm: Any = None, mcp_manager: Any = None, pool: Any = None):
        self.registry = registry
        self.llm = llm
        self.mcp_manager = mcp_manager
        self.pool = pool


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
