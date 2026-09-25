"""Skill-local context slicing（Plan-F Context Pipeline P2）：修嵌套上下文膨胀。

Skill 调用时不再全量携带父 context，改为传递 **context 切片**：

- ``inherited``：父任务 goal + 关键约束（来自 ``TaskState``，非全量消息）；
- ``task_specific``：本次调用参数；
- ``memory``：经 ``MemoryGate`` 的相关记忆。

父 agent 只收到子 skill 的**结果摘要**（同样走 tool_result 压缩规则），
嵌套 token 从乘法变加法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.context.tool_result import ToolResultCompressor


@dataclass
class SkillInvocationContext:
    """Skill 调用局部上下文：父级只传切片，不传全量消息。

    ``to_prompt_text()`` 把切片渲染为注入子 agent 的提示文本。
    """

    inherited: dict[str, Any] = field(default_factory=dict)
    task_specific: dict[str, Any] = field(default_factory=dict)
    memory: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """把切片渲染为纯文本提示（供子 agent 的 system/user 注入）。"""
        lines: list[str] = []

        if self.inherited:
            lines.append("## 父任务上下文")
            for key, value in self.inherited.items():
                lines.append(f"- {key}: {value}")

        if self.task_specific:
            lines.append("## 本次任务参数")
            for key, value in self.task_specific.items():
                lines.append(f"- {key}: {value}")

        if self.memory:
            lines.append("## 相关记忆")
            for m in self.memory:
                lines.append(f"- {m}")

        return "\n".join(lines)

    @property
    def empty(self) -> bool:
        return not (self.inherited or self.task_specific or self.memory)


def slice_skill_context(
    *,
    task_snapshot: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    gated_memory: list[str] | None = None,
    inherit_keys: tuple[str, ...] = ("goal", "constraints"),
) -> SkillInvocationContext:
    """从任务快照 + 调用参数 + 门控记忆构造 Skill 局部上下文切片。

    ``task_snapshot``：``AgentContext.snapshot()["task"]``（goal / completed_steps /
    pending / constraints）。只抽取 ``inherit_keys`` 指定的字段（默认 goal + constraints），
    避免把全部执行状态塞给子 skill。

    ``params``：本次 Skill 调用参数（task_specific）。
    ``gated_memory``：经 ``MemoryGate`` 过滤后的相关记忆。
    """
    inherited: dict[str, Any] = {}
    if task_snapshot and isinstance(task_snapshot, dict):
        # 兼容传入完整 AgentContext.snapshot()（含 "task" 键）或直接传入 task 子 dict
        nested = task_snapshot.get("task")
        source: dict[str, Any] = nested if isinstance(nested, dict) else task_snapshot
        for key in inherit_keys:
            if key not in source:
                continue
            value = source[key]
            if isinstance(value, (list, tuple, dict)) and value:
                inherited[key] = value
            elif value not in ("", None):
                inherited[key] = value

    return SkillInvocationContext(
        inherited=inherited,
        task_specific=dict(params or {}),
        memory=list(gated_memory or []),
    )


async def summarize_child_result(
    result: Any, *, max_tokens: int = 2048, store_dir=None
) -> dict[str, Any]:
    """子 Skill 结果摘要（走 tool_result 压缩规则）：父 agent 只收摘要 + ref。

    返回 ``{"text", "ref", "full_path", "truncated"}``（见 ToolResultCompressor）。
    """
    return ToolResultCompressor(max_tokens=max_tokens, store_dir=store_dir).compress(result)