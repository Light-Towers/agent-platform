"""统一线程状态契约（Plan-F P2）。

双 Planner（DeterministicPlanner / AgenticPlanner）共享同一会话（thread）时，
checkpoint 中的历史状态必须采用统一 schema，否则切换 Planner 后状态格式不兼容
（app 的 ``AgentState`` 含 route/evidence/iterations/mcp_* 编排字段，联邦是纯
LangChain messages——两套形态不能直接共存于一个 checkpointer）。

设计（契约层零框架依赖，不 import langchain）：
- ``messages``: LangChain BaseMessage 的序列化形态（``dict``）。契约层不依赖
  langchain-core；``BaseMessage <-> dict`` 转换由 agent-runtime 适配层提供。
- ``metadata``: 编排状态。app 的 route/evidence/iterations 等归入此段，
  planner 各自读写自己的子集，互不干扰。
- ``version``: 契约版本，未来演进时用于迁移。

Planner 侧用法约定：
- DeterministicPlanner 把 ``AgentState`` 的编排字段写入 ``metadata``，
  把历史对话写入 ``messages``。
- AgenticPlanner 把 LangChain messages 序列化后写入 ``messages``，
  元数据（如子代理痕迹）写入 ``metadata``。
"""

from typing import Any

from pydantic import BaseModel, Field

# 当前契约版本。破坏性变更时递增并保留迁移逻辑。
THREAD_STATE_VERSION = 1


class ThreadState(BaseModel):
    """统一线程状态：消息流 + 编排元数据两段式。"""

    thread_id: str = Field(default="", description="会话/线程标识")
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="LangChain BaseMessage 序列化形态（role/content/tool_calls 等）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="编排状态（route/evidence/iterations/mcp_* 等），planner 各自读写子集",
    )
    version: int = Field(default=THREAD_STATE_VERSION, description="契约版本")


def message_dict(role: str, content: str, **extra: Any) -> dict[str, Any]:
    """构造一条消息 dict（契约层便捷函数，供适配层组装 messages）。"""
    return {"role": role, "content": content, **extra}


def empty_thread_state(thread_id: str) -> ThreadState:
    """创建空 ThreadState（thread_id 已指定）。"""
    return ThreadState(thread_id=thread_id)
