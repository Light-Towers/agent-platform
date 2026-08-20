"""Context Manager（Plan-F）：统一管理 Agent 执行期的三类上下文。

架构契约（对应理想架构 Q5）：不把所有状态塞进 LLM prompt，而是结构化分离：

- ``ConversationContext``：对话历史（可能被压缩 / 截断，受 context window 影响）；
- ``TaskState``：当前任务状态（goal / completed_steps / pending / constraints）；
- ``ExecutionState``：Skill 执行状态（outputs / errors / skill_stack）。

``ContextManager`` 管理这三类的生命周期，提供结构化快照（``snapshot``，供 LLM prompt
注入或持久化）与状态更新（供 Planner / 执行器消费事件）。Skill Definition 不会遗忘
（在 SkillRegistry 静态持有）；可能被压缩的是 ConversationContext；TaskState /
ExecutionState 由 ContextManager 结构化保存，不依赖 prompt 完整性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationContext:
    """对话历史：消息列表 + 压缩标记。"""

    messages: list[Any] = field(default_factory=list)
    compacted: bool = False

    def append(self, message: Any) -> None:
        self.messages.append(message)
        self.compacted = False


@dataclass
class TaskState:
    """任务状态：目标 + 已完成步骤 + 待办 + 约束。"""

    goal: str = ""
    completed_steps: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)

    def mark_completed(self, step: str) -> None:
        if step in self.pending:
            self.pending.remove(step)
        if step not in self.completed_steps:
            self.completed_steps.append(step)

    def add_pending(self, step: str) -> None:
        if step not in self.pending and step not in self.completed_steps:
            self.pending.append(step)


@dataclass
class ExecutionState:
    """Skill 执行状态：输出 + 错误 + 调用栈。"""

    outputs: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    skill_stack: list[str] = field(default_factory=list)

    def record_output(self, skill: str, result: Any) -> None:
        self.outputs[skill] = result

    def record_error(self, skill: str, error: str) -> None:
        self.errors[skill] = error


@dataclass
class AgentContext:
    """统一 Agent 上下文：对话 + 任务 + 执行状态。"""

    conversation: ConversationContext = field(default_factory=ConversationContext)
    task: TaskState = field(default_factory=TaskState)
    execution: ExecutionState = field(default_factory=ExecutionState)
    metadata: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """结构化快照：供 LLM prompt 注入或持久化。"""
        return {
            "conversation": {
                "message_count": len(self.conversation.messages),
                "compacted": self.conversation.compacted,
            },
            "task": {
                "goal": self.task.goal,
                "completed_steps": list(self.task.completed_steps),
                "pending": list(self.task.pending),
                "constraints": dict(self.task.constraints),
            },
            "execution": {
                "outputs": dict(self.execution.outputs),
                "errors": dict(self.execution.errors),
                "skill_stack": list(self.execution.skill_stack),
            },
            "metadata": dict(self.metadata),
        }


class ContextManager:
    """上下文管理器：创建 / 更新 / 快照 ``AgentContext``。

    用法::

        cm = ContextManager()
        ctx = cm.create_context(goal="分析项目架构")
        cm.update_task(ctx, completed="fetch_repo")
        snapshot = cm.snapshot(ctx)  # 注入 prompt 或持久化
    """

    def create_context(
        self,
        goal: str = "",
        messages: list[Any] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> AgentContext:
        ctx = AgentContext()
        ctx.task.goal = goal
        if messages:
            ctx.conversation.messages = list(messages)
        if constraints:
            ctx.task.constraints = dict(constraints)
        return ctx

    def update_task(
        self,
        ctx: AgentContext,
        *,
        completed: str | None = None,
        pending: str | None = None,
    ) -> None:
        if completed:
            ctx.task.mark_completed(completed)
        if pending:
            ctx.task.add_pending(pending)

    def record_skill(
        self,
        ctx: AgentContext,
        skill: str,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        if error is not None:
            ctx.execution.record_error(skill, error)
        elif result is not None:
            ctx.execution.record_output(skill, result)

    def snapshot(self, ctx: AgentContext) -> dict[str, Any]:
        """结构化快照（代理 ``AgentContext.snapshot``）。"""
        return ctx.snapshot()
