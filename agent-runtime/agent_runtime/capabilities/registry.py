"""Capability Registry：能力层中立化（Plan-F Phase 1）。

定位：统一"能力"的注册 / 发现 / 执行入口。三种执行器：
- FunctionExecutor：进程内确定性函数（app 的 search/rag/sql/mcp）
- AgentExecutor：本地 subagent（LLM self-reasoning，联邦 database/network/knowledge 三 agent）
- RemoteExecutor：远程子服务（Agent Protocol / HTTP）

契约（P1）：Planner 只决策（plan），执行统一走 CapabilityRegistry.execute()——
retry / 超时 / 熔断等 Runtime 边界在此收敛，Planner 不持有执行语义。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

# 执行器签名：**kwargs 透传（如 search(query=...)、mcp(state=..., mcp_manager=...)）
Executor = Callable[..., Awaitable[Any]]


class CapabilityKind(str, Enum):
    """能力执行方式：决定走哪个执行器语义。"""

    FUNCTION = "function"
    AGENT = "agent"
    REMOTE = "remote"


@dataclass(frozen=True)
class Capability:
    """注册表条目：能力契约（不可变）。"""

    name: str
    description: str
    kind: CapabilityKind
    executor: Executor
    timeout_ms: int | None = None
    # 保留扩展位：metadata（来源轨/是否降级/评估标签等）后续按需填充
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityNotFoundError(KeyError):
    """执行/获取不存在的能力。"""


class DuplicateCapabilityError(ValueError):
    """重复注册同名能力。"""


class CapabilityRegistry:
    """能力注册表：注册 / 发现 / 统一执行入口。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._capabilities:
            raise DuplicateCapabilityError(
                f"能力已注册: {capability.name}（重复注册会掩盖行为差异，拒绝覆盖）"
            )
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability:
        try:
            return self._capabilities[name]
        except KeyError:
            raise CapabilityNotFoundError(f"能力未注册: {name}") from None

    def list(self) -> list[Capability]:
        """按名称排序返回全部能力。"""
        return sorted(self._capabilities.values(), key=lambda c: c.name)

    def __contains__(self, name: str) -> bool:
        return name in self._capabilities

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """统一执行入口：按能力配置应用 Runtime 边界（超时），kwargs 透传。"""
        capability = self.get(name)
        coro = capability.executor(**kwargs)
        if capability.timeout_ms is not None:
            coro = asyncio.wait_for(coro, timeout=capability.timeout_ms / 1000)
        return await coro
