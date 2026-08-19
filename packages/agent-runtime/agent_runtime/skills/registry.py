"""Skill Registry：能力层中立化（Plan-F Phase 1）。

定位：统一"能力"的注册 / 发现 / 执行入口。三种执行器：
- FunctionExecutor：进程内确定性函数（app 的 search/rag/sql/mcp）
- AgentExecutor：本地 subagent（LLM self-reasoning，联邦 database/network/knowledge 三 agent）
- RemoteExecutor：远程子服务（Agent Protocol / HTTP）

契约（P1）：Planner 只决策（plan），执行统一走 SkillRegistry.execute()——
retry / 超时 / 熔断等 Runtime 边界在此收敛，Planner 不持有执行语义。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

# 执行器签名：**kwargs 透传（如 search(query=...)、mcp(state=..., mcp_manager=...)）
Executor = Callable[..., Awaitable[Any]]


class SkillKind(str, Enum):
    """能力执行方式：决定走哪个执行器语义。"""

    FUNCTION = "function"
    AGENT = "agent"
    REMOTE = "remote"
    WORKFLOW = "workflow"  # Workflow Skill：Static/Conditional 编排（graph.py → general_qa），LangGraph 仅是执行实现


@dataclass(frozen=True)
class Skill:
    """注册表条目：能力契约（不可变）。

    input_schema / output_schema（可选 JSON Schema dict）是 Skill 契约升级（Phase 1.5）：
    Planner / Agent 组合调用时经 ``to_tool_schema()`` 生成工具描述与入参校验，
    能力实现细节（Python 函数 / 静态 DAG / 远程服务）对调用方保持黑盒。
    """

    name: str
    description: str
    kind: SkillKind
    executor: Executor
    timeout_ms: int | None = None
    # 保留扩展位：metadata（来源轨/是否降级/评估标签等）后续按需填充
    metadata: dict[str, Any] = field(default_factory=dict)
    # Skill 契约（Phase 1.5）：JSON Schema dict，缺省时 Agent 只见 name/description
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    def to_tool_schema(self) -> dict[str, Any]:
        """生成 Agent 工具描述（供 Planner / Agent 组合调用时注入工具列表）。

        与 MCP/OpenAI function calling 同构：name + description + parameters。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema
                or {"type": "object", "properties": {}},
            },
        }


class SkillNotFoundError(KeyError):
    """执行/获取不存在的能力。"""


class DuplicateSkillError(ValueError):
    """重复注册同名能力。"""


class SkillExecutionError(RuntimeError):
    """Skill 执行失败：入参契约校验不通过（给出明确错误，而非内部 Python exception）。"""


def _validate_input(name: str, schema: dict[str, Any] | None, kwargs: dict[str, Any]) -> None:
    """Skill 入参契约校验（轻量）：required 字段存在性 + properties 类型检查。

    schema 缺省（None）跳过；仅校验公开业务入参，不拒绝额外注入参数
    （如 mcp 的 state/mcp_manager 由注册方透传，不属于公开契约）。
    """
    if not schema:
        return
    missing = [k for k in schema.get("required", []) if k not in kwargs]
    if missing:
        raise SkillExecutionError(
            f"Skill {name} 入参契约校验失败: 缺少必填参数 {missing}"
        )
    properties = schema.get("properties", {})
    for key, value in kwargs.items():
        prop = properties.get(key)
        if not prop or value is None:
            continue
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            raise SkillExecutionError(
                f"Skill {name} 入参契约校验失败: 参数 {key} 期望 {expected}，"
                f"实际 {type(value).__name__}"
            )
        if expected in ("number", "integer") and isinstance(value, bool):
            raise SkillExecutionError(
                f"Skill {name} 入参契约校验失败: 参数 {key} 期望 {expected}，"
                f"实际 bool"
            )
        if expected == "number" and not isinstance(value, (int, float)):
            raise SkillExecutionError(
                f"Skill {name} 入参契约校验失败: 参数 {key} 期望 {expected}，"
                f"实际 {type(value).__name__}"
            )
        if expected == "integer" and not isinstance(value, int):
            raise SkillExecutionError(
                f"Skill {name} 入参契约校验失败: 参数 {key} 期望 {expected}，"
                f"实际 {type(value).__name__}"
            )
        if expected == "boolean" and not isinstance(value, bool):
            raise SkillExecutionError(
                f"Skill {name} 入参契约校验失败: 参数 {key} 期望 {expected}，"
                f"实际 {type(value).__name__}"
            )


class SkillRegistry:
    """能力注册表：注册 / 发现 / 统一执行入口。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, Skill] = {}

    def register(self, capability: Skill) -> None:
        if capability.name in self._capabilities:
            raise DuplicateSkillError(
                f"能力已注册: {capability.name}（重复注册会掩盖行为差异，拒绝覆盖）"
            )
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Skill:
        try:
            return self._capabilities[name]
        except KeyError:
            raise SkillNotFoundError(f"能力未注册: {name}") from None

    def list(self) -> list[Skill]:
        """按名称排序返回全部能力。"""
        return sorted(self._capabilities.values(), key=lambda c: c.name)

    def __contains__(self, name: str) -> bool:
        return name in self._capabilities

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """统一执行入口：入参契约校验 → Runtime 边界（超时），kwargs 透传。"""
        capability = self.get(name)
        _validate_input(name, capability.input_schema, kwargs)
        coro = capability.executor(**kwargs)
        if capability.timeout_ms is not None:
            coro = asyncio.wait_for(coro, timeout=capability.timeout_ms / 1000)
        return await coro
