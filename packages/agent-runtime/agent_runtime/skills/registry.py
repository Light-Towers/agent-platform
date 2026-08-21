"""Skill Registry：能力层中立化（Plan-F Phase 1）。

定位：统一"能力"的注册 / 发现 / 执行入口。四种执行器：
- FunctionExecutor：进程内确定性函数（app 的 search/rag/sql/mcp）
- AgentExecutor：本地 subagent（LLM self-reasoning，联邦 database/network/knowledge 三 agent）
- RemoteExecutor：远程子服务（Agent Protocol / HTTP）
- WorkflowExecutor：Static/Conditional 编排（graph.py → general_qa），LangGraph 仅是执行实现

契约（P1）：Planner 只决策（plan），执行统一走 SkillRegistry.execute()。
execute() 承载的 Runtime 边界：**入参契约校验 + 统一超时（最内层）+
可选中间件洋葱链**（retry / 熔断 / rate limit / tracing 收敛于此，
见 ``agent_runtime/skills/middleware.py``；已落地熔断，retry/rate limit 演进中）。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_runtime.skills.middleware import SkillMiddleware

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
    # 权限声明（Plan-F 组合治理）：空 frozenset 表示无限制（公开能力）；
    # 非空时调用方须持有全部声明权限方可发现/调用（PolicyValidator 校验）。
    permissions: frozenset[str] = field(default_factory=frozenset)
    # 组合声明（Plan-F 一等公民组合模型）：本能力直接组合的下层能力名列表。
    # 须经 Runtime/Registry（runtime.delegate）组合，由 CompositionValidator 静态校验
    # （存在性 / 环 / 权限闭包），避免组合治理仅靠运行时 skill_guard 兜底。
    sub_skills: tuple[str, ...] = field(default_factory=tuple)

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


_TOKEN_RE = re.compile(r"[^\W_]+")


def _tokenize(text: str) -> list[str]:
    """轻量分词：按单词字符切分并小写化，连续中文段按字符拆分（不引入外部 NLP 依赖）。

    供 SkillRegistry.discover 的关键词匹配打分；语义检索演进时替换为
    embedding retriever 即可，discover 接口不变。
    """
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        # ASCII 词直接保留；连续中文段（长度 > 1 且非 ASCII）按字符拆分提升匹配粒度
        if len(raw) > 1 and any(ord(c) > 127 for c in raw):
            tokens.extend(c.lower() for c in raw if ord(c) > 127)
            ascii_parts = [w.lower() for w in re.findall(r"[a-z0-9]+", raw, re.IGNORECASE)]
            tokens.extend(ascii_parts)
        else:
            tokens.append(raw.lower())
    return tokens


def _validate_output(name: str, schema: dict[str, Any] | None, result: Any) -> None:
    """Skill 产出契约校验（轻量）：type 匹配 + object required 字段存在性。

    schema 缺省（None）跳过；仅校验常见类型（string/object/array/number/integer/boolean），
    不做完整 JSON Schema 验证（避免引入 jsonschema 依赖）。
    """
    if not schema:
        return
    expected = schema.get("type")
    if expected == "string" and not isinstance(result, str):
        raise SkillExecutionError(
            f"Skill {name} 产出校验失败: 期望 string，实际 {type(result).__name__}"
        )
    if expected == "object" and not isinstance(result, dict):
        raise SkillExecutionError(
            f"Skill {name} 产出校验失败: 期望 object，实际 {type(result).__name__}"
        )
    if expected == "array" and not isinstance(result, list):
        raise SkillExecutionError(
            f"Skill {name} 产出校验失败: 期望 array，实际 {type(result).__name__}"
        )
    if expected in ("number", "integer") and not isinstance(result, (int, float)):
        raise SkillExecutionError(
            f"Skill {name} 产出校验失败: 期望 {expected}，实际 {type(result).__name__}"
        )
    if expected == "boolean" and not isinstance(result, bool):
        raise SkillExecutionError(
            f"Skill {name} 产出校验失败: 期望 boolean，实际 {type(result).__name__}"
        )
    if expected == "object" and isinstance(result, dict):
        missing = [k for k in schema.get("required", []) if k not in result]
        if missing:
            raise SkillExecutionError(
                f"Skill {name} 产出校验失败: 缺少必填字段 {missing}"
            )


class SkillRegistry:
    """能力注册表：注册 / 发现 / 统一执行入口。

    ``middlewares``：Skill 执行洋葱链（可选）。链上边界按注册顺序
    外层→内层包裹最终执行器，最先注册的最外层。
    """

    def __init__(self, middlewares: list[SkillMiddleware] | None = None) -> None:
        self._capabilities: dict[str, Skill] = {}
        self._middlewares: list[SkillMiddleware] = list(middlewares or [])

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

    def validate_composition(self) -> list[str]:
        """静态校验 Skill 组合图（§7.1 一等公民组合模型）。

        委托 ``CompositionValidator`` 检查：存在性 / 权限闭包 / 无环。
        ``PlannerRuntime.execution()`` 进入时也会自动跑（fail-fast），本方法供
        启动期 / 测试显式校验组合图合法性。
        """
        from agent_runtime.skills.composition import CompositionValidator

        return CompositionValidator(self).validate()

    def assert_composition_valid(self) -> None:
        """组合图非法时抛 ``CompositionError``（fail-fast，供 execution 入口调用）。"""
        from agent_runtime.skills.composition import CompositionError, CompositionValidator

        violations = CompositionValidator(self).validate()
        if violations:
            raise CompositionError("; ".join(violations))

    def __contains__(self, name: str) -> bool:
        return name in self._capabilities

    def discover(
        self,
        query: str = "",
        *,
        top_k: int = 10,
        metadata_filter: dict[str, Any] | None = None,
        caller_permissions: frozenset[str] | set[str] | None = None,
    ) -> list[Skill]:
        """发现候选 Skill：metadata 过滤 → 权限过滤 → 关键词打分 → top_k 截断。

        架构契约（Plan-F Skill Discovery）：Planner 不应把全量 Skill schema 塞进 LLM 上下文，
        而是先经 discover 缩小候选集，再交 LLM 决策。三阶段过滤互不依赖、可独立跳过：

        - ``metadata_filter``：按 ``skill.metadata[k] == v`` 精确匹配（来源轨/标签/降级标记等）；
        - ``caller_permissions``：``skill.permissions`` 非空时须 ⊆ ``caller_permissions``（空 permissions
          表示公开能力，始终通过）；
        - ``query`` 关键词打分：query 词集 ∩ (name ∪ description) 词集的大小，降序排序。

        语义检索演进位：当前用关键词匹配（零依赖），后续可插入 embedding retriever
        （替换 ``_score`` 即可，discover 接口不变）。
        """
        candidates = list(self._capabilities.values())
        if metadata_filter:
            candidates = [
                s
                for s in candidates
                if all(s.metadata.get(k) == v for k, v in metadata_filter.items())
            ]
        if caller_permissions is not None:
            allowed = frozenset(caller_permissions)
            candidates = [
                s for s in candidates if not s.permissions or s.permissions <= allowed
            ]
        if query:
            scored = [(self._score(query, s), s) for s in candidates]
            scored.sort(key=lambda pair: (-pair[0], pair[1].name))
            candidates = [s for _, s in scored]
        else:
            candidates.sort(key=lambda s: s.name)
        return candidates[:top_k]

    @staticmethod
    def _score(query: str, skill: Skill) -> int:
        """关键词匹配得分：query 词集与 skill name/description 词集的交集大小。"""
        q_words = set(_tokenize(query))
        if not q_words:
            return 0
        s_words = set(_tokenize(skill.name)) | set(_tokenize(skill.description))
        return len(q_words & s_words)

    @staticmethod
    def to_tool_schemas(skills: list[Skill]) -> list[dict[str, Any]]:
        """批量生成工具描述（供 Planner / Agent 注入 LLM 工具列表）。"""
        return [s.to_tool_schema() for s in skills]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """统一执行入口：入参契约校验 → 中间件洋葱链 → 执行器（含统一超时）→ 产出契约校验。"""
        capability = self.get(name)
        _validate_input(name, capability.input_schema, kwargs)

        async def invoke(n: str, kw: dict[str, Any]) -> Any:
            coro = capability.executor(**kw)
            if capability.timeout_ms is not None:
                coro = asyncio.wait_for(coro, timeout=capability.timeout_ms / 1000)
            result = await coro
            _validate_output(name, capability.output_schema, result)
            return result

        # 洋葱链：先注册的外层先执行，经 call_next 逐层向内，直到最终执行器。
        # 链为空的常规路径与逐层委托等价（无中间件时 zero 额外开销）。
        if not self._middlewares:
            return await invoke(name, kwargs)
        handler: Callable[[str, dict[str, Any]], Awaitable[Any]] = invoke
        for middleware in reversed(self._middlewares):
            prev = handler
            handler = lambda n, kw, _mw=middleware, _prev=prev: _mw.around(n, kw, _prev)
        return await handler(name, kwargs)
