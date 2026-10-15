"""V3 补-1 **接线**单测：`__awaitable__(kind="human")` → HumanTaskStore + 挂起 kind 透传。

与既有 ``test_human_task.py`` 的分工（刻意不重复）：
- ``test_human_task.py`` 覆盖 store/resolver 的**内部**状态流转，其中 ``WAITING_HUMAN → RUNNING``
  是**手动 seed** 出 ``WAITING_HUMAN`` 再断言 resume——正是这个手动 seed 掩盖了「生产里
  ``WAITING_HUMAN`` 从不被写入」的事实，使 resolver 的 resume 分支沦为死代码。
- 本文件覆盖**接线**：生产里 ``WAITING_HUMAN`` 究竟怎么被写出来——
  ① ``protocol.delegate`` 按 ``result["kind"] == "human"`` 分派到 ``HumanTaskStore``（而非一律 EXTERNAL）；
  ② 未注入 ``human_task_store`` 时**逐字退回** EXTERNAL（回归锁 + 装配缺口的优雅降级）；
  ③ ``execution_graph`` 把 ``ExecutionSuspended.kind`` 透传进 ``suspended`` 事件 payload
     （``query_router._suspend_status`` 据此选 ``WAITING_HUMAN`` / ``WAITING_EXTERNAL``）；
  ④ ``HumanTaskStore.create(generation=...)`` 把 lease generation 盖到回执上（与 EXTERNAL 同源 fencing）。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    InMemoryAwaitableTaskStore,
)
from agent_runtime.human_task import HumanTask, HumanTaskStore
from agent_runtime.planner.execution_graph import ExecutionGraph, execute_graph
from agent_runtime.planner.protocol import PlannerRuntime, StreamEvent
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry

# ── helpers ──────────────────────────────────────────────────────────────────


async def _human_awaitable_skill(**kwargs: Any) -> dict[str, Any]:
    """请求人工审批的可等待 Skill（kind="human"）。"""
    return {
        "__awaitable__": True,
        "kind": "human",
        "prompt": "请审批此变更",
        "options": ["approve", "reject"],
        "approver": "manager_a",
        "context": {"amount": 50000},
    }


async def _external_awaitable_skill(**kwargs: Any) -> dict[str, Any]:
    """普通外部异步 Skill（无 kind=human，走既有 EXTERNAL 路径）。"""
    return {"__awaitable__": True, "task_id": "job-1", "provider": "acme"}


def _registry(name: str, fn) -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill(name, name, SkillKind.FUNCTION, fn))
    return reg


def _single_node_graph(skill_name: str) -> ExecutionGraph:
    g = ExecutionGraph()
    g.add_node("n1", skill_name, kwargs={"q": "x"})
    return g


async def _collect(graph: ExecutionGraph, runtime: PlannerRuntime, execution_id: str) -> list[StreamEvent]:
    return [ev async for ev in execute_graph(graph, runtime, execution_id=execution_id)]


def _suspended(events: list[StreamEvent]) -> StreamEvent:
    found = [e for e in events if e.type == "suspended"]
    assert len(found) == 1, f"expected exactly 1 suspended event, got {len(found)}"
    return found[0]


# ── ① human 分派 ─────────────────────────────────────────────────────────────


async def test_awaitable_human_dispatches_to_human_task_store():
    """kind="human" + 注入了 human_task_store → 经 HumanTaskStore.create 建 HUMAN 任务。"""
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)
    runtime = PlannerRuntime(
        registry=_registry("ask_approval", _human_awaitable_skill),
        awaitable_task_store=awaitable_store,
        human_task_store=human_store,
    )

    events = await _collect(_single_node_graph("ask_approval"), runtime, "exec-h1")
    susp = _suspended(events)
    assert susp.payload["kind"] == "human"

    tasks = await awaitable_store.list_by_execution("exec-h1")
    assert len(tasks) == 1
    task = tasks[0]
    assert task.kind is AwaitableKind.HUMAN
    assert task.state is AwaitableState.PENDING  # HumanTaskStore.create 建 PENDING（非 EXTERNAL 的 SUBMITTED）
    assert task.metadata["prompt"] == "请审批此变更"
    assert task.metadata["options"] == ["approve", "reject"]
    assert task.metadata["approver"] == "manager_a"
    assert task.metadata["context"] == {"skill_name": "ask_approval", "request": {"amount": 50000}}
    # 挂起事件的 task_id 指向同一条任务（callback / 审批面据此收敛）
    assert susp.payload["task_id"] == task.task_id
    # node_id 承载的是 delegate 的 skill 名（既有语义，EXTERNAL/HUMAN 两路一致），非图节点 id
    assert susp.payload["node_id"] == "ask_approval"


# ── ② EXTERNAL 回归锁 ────────────────────────────────────────────────────────


async def test_awaitable_external_path_unchanged():
    """无 kind="human" → 逐字走既有 EXTERNAL 路径（state=SUBMITTED + provider_task_id）。"""
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)
    runtime = PlannerRuntime(
        registry=_registry("ext_job", _external_awaitable_skill),
        awaitable_task_store=awaitable_store,
        human_task_store=human_store,
    )

    events = await _collect(_single_node_graph("ext_job"), runtime, "exec-e1")
    susp = _suspended(events)
    # ExecutionSuspended.kind 缺省 None → payload 落 "external"（query_router 据此写 WAITING_EXTERNAL）
    assert susp.payload["kind"] == "external"

    tasks = await awaitable_store.list_by_execution("exec-e1")
    assert len(tasks) == 1
    task = tasks[0]
    assert task.kind is AwaitableKind.EXTERNAL
    assert task.state is AwaitableState.SUBMITTED
    assert task.provider_task_id == "job-1"
    assert task.provider == "acme"


# ── ③ 未装配 human_task_store 的降级 ────────────────────────────────────────


async def test_awaitable_human_without_store_falls_back_to_external():
    """kind="human" 但**未注入** human_task_store → 退回 EXTERNAL 挂起（不崩，挂起仍可用）。

    这是装配缺口的优雅降级：callback 仍能收敛，只是没有审批面。不得升级成运行期失败。
    """
    awaitable_store = InMemoryAwaitableTaskStore()
    runtime = PlannerRuntime(
        registry=_registry("ask_approval", _human_awaitable_skill),
        awaitable_task_store=awaitable_store,
        # human_task_store 刻意不注入
    )

    events = await _collect(_single_node_graph("ask_approval"), runtime, "exec-h2")
    susp = _suspended(events)
    assert susp.payload["kind"] == "external"

    tasks = await awaitable_store.list_by_execution("exec-h2")
    assert len(tasks) == 1
    assert tasks[0].kind is AwaitableKind.EXTERNAL


# ── ④ generation 盖章（与 EXTERNAL 同源 fencing）─────────────────────────────


async def test_human_store_create_stamps_generation():
    """create(generation=N) 把 lease generation 盖到回执——takeover 后 zombie writer 写不进。"""
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    awaitable = await human_store.create(task, generation=7)
    assert awaitable.generation == 7

    loaded = await awaitable_store.load(awaitable.task_id)
    assert loaded is not None
    assert loaded.generation == 7


async def test_human_store_create_generation_defaults_none():
    """不传 generation → None（来源未知，不参与 fence；与存量行同语义）。"""
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    awaitable = await human_store.create(task)
    assert awaitable.generation is None
