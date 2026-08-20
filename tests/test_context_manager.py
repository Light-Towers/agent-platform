"""Context Manager 测试（Plan-F）：三类上下文分离 + 结构化快照。"""

from __future__ import annotations

from agent_runtime.planner.context_manager import (
    AgentContext,
    ContextManager,
    ConversationContext,
    ExecutionState,
    TaskState,
)

# ---------- 三类上下文 ----------


def test_conversation_context_append():
    conv = ConversationContext()
    conv.append("hello")
    assert conv.messages == ["hello"]
    assert conv.compacted is False


def test_task_state_mark_completed():
    task = TaskState(goal="分析", pending=["fetch", "analyze"])
    task.mark_completed("fetch")
    assert task.completed_steps == ["fetch"]
    assert task.pending == ["analyze"]


def test_task_state_add_pending():
    task = TaskState(goal="g")
    task.add_pending("step_a")
    task.add_pending("step_a")  # 去重
    assert task.pending == ["step_a"]


def test_execution_state_record():
    exec_state = ExecutionState()
    exec_state.record_output("search", ["result1"])
    exec_state.record_error("rag", "timeout")
    assert exec_state.outputs["search"] == ["result1"]
    assert exec_state.errors["rag"] == "timeout"


# ---------- ContextManager ----------


def test_create_context_defaults():
    cm = ContextManager()
    ctx = cm.create_context()
    assert ctx.task.goal == ""
    assert ctx.conversation.messages == []
    assert ctx.task.constraints == {}


def test_create_context_with_params():
    cm = ContextManager()
    ctx = cm.create_context(goal="分析架构", messages=["hi"], constraints={"lang": "py"})
    assert ctx.task.goal == "分析架构"
    assert ctx.conversation.messages == ["hi"]
    assert ctx.task.constraints == {"lang": "py"}


def test_update_task():
    cm = ContextManager()
    ctx = cm.create_context(goal="g")
    cm.update_task(ctx, pending="step_a")
    cm.update_task(ctx, pending="step_b")
    cm.update_task(ctx, completed="step_a")
    assert ctx.task.completed_steps == ["step_a"]
    assert ctx.task.pending == ["step_b"]


def test_record_skill_output():
    cm = ContextManager()
    ctx = cm.create_context()
    cm.record_skill(ctx, "search", result=["e1"])
    assert ctx.execution.outputs["search"] == ["e1"]


def test_record_skill_error():
    cm = ContextManager()
    ctx = cm.create_context()
    cm.record_skill(ctx, "search", error="timeout")
    assert ctx.execution.errors["search"] == "timeout"


# ---------- snapshot ----------


def test_snapshot_structure():
    cm = ContextManager()
    ctx = cm.create_context(goal="g", messages=["m1", "m2"])
    cm.update_task(ctx, pending="step_a")
    cm.record_skill(ctx, "search", result="ok")

    snap = cm.snapshot(ctx)
    assert snap["conversation"]["message_count"] == 2
    assert snap["conversation"]["compacted"] is False
    assert snap["task"]["goal"] == "g"
    assert snap["task"]["pending"] == ["step_a"]
    assert snap["execution"]["outputs"]["search"] == "ok"


def test_agent_context_snapshot_direct():
    ctx = AgentContext()
    ctx.task.goal = "test"
    ctx.execution.skill_stack.append("a")
    snap = ctx.snapshot()
    assert snap["task"]["goal"] == "test"
    assert snap["execution"]["skill_stack"] == ["a"]
