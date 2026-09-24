"""四类 Memory 阶段 1 单测：WorkingMemory + SemanticMemory + MemoryTypes。

验证：
- WorkingMemorySnapshot：快照属性（completed_nodes / is_running / is_waiting / pending_awaitables）；
- WorkingMemory：组合 Checkpoint + Status + Awaitable 的门面；
- SemanticMemory：共享 + 用户两级召回边界；
- MemoryCategory / MemoryRetriever / ContextSelector：召回编排。
"""


from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    InMemoryAwaitableTaskStore,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    InMemoryExecutionStatusStore,
)
from agent_runtime.memory_types import (
    ContextSelector,
    MemoryCategory,
    MemoryRecallRequest,
    MemoryRetriever,
)
from agent_runtime.planner.durability import Checkpoint, InMemoryCheckpointStore
from agent_runtime.semantic_memory import (
    SemanticMemory,
    SemanticRecallRequest,
    SemanticRecallResult,
    SharedSemanticStore,
    UserSemanticStore,
)
from agent_runtime.working_memory import WorkingMemory, WorkingMemorySnapshot

# ===== WorkingMemorySnapshot =====

def test_snapshot_empty():
    snap = WorkingMemorySnapshot(execution_id="e1")
    assert snap.completed_nodes == []
    assert not snap.is_running
    assert not snap.is_waiting
    assert snap.pending_awaitables == []


def test_snapshot_with_checkpoint():
    cp = Checkpoint("e1", {"n1": "r1", "n2": "r2"})
    snap = WorkingMemorySnapshot(execution_id="e1", checkpoint=cp)
    assert snap.completed_nodes == ["n1", "n2"]


def test_snapshot_running():
    snap = WorkingMemorySnapshot(execution_id="e1", status=ExecutionStatus.RUNNING)
    assert snap.is_running
    assert not snap.is_waiting


def test_snapshot_waiting():
    snap = WorkingMemorySnapshot(
        execution_id="e1", status=ExecutionStatus.WAITING_EXTERNAL
    )
    assert snap.is_waiting
    assert not snap.is_running


def test_snapshot_terminal():
    snap = WorkingMemorySnapshot(execution_id="e1", status=ExecutionStatus.SUCCEEDED)
    assert snap.is_terminal


def test_snapshot_pending_awaitables():
    t1 = AwaitableTask(
        execution_id="e1", step_id="n1", kind=AwaitableKind.EXTERNAL, provider="api",
        state=AwaitableState.PENDING,
    )
    t2 = AwaitableTask(
        execution_id="e1", step_id="n2", kind=AwaitableKind.HUMAN, provider="human",
        state=AwaitableState.COMPLETED,
    )
    snap = WorkingMemorySnapshot(execution_id="e1", awaitable_tasks=[t1, t2])
    assert len(snap.pending_awaitables) == 1
    assert snap.pending_awaitables[0].step_id == "n1"


# ===== WorkingMemory =====

async def test_working_memory_snapshot():
    ckpt_store = InMemoryCheckpointStore()
    status_store = InMemoryExecutionStatusStore()
    awaitable_store = InMemoryAwaitableTaskStore()

    wm = WorkingMemory(ckpt_store, status_store, awaitable_store)

    await ckpt_store.save(Checkpoint("e1", {"n1": "r1"}))
    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING, generation=1))
    await awaitable_store.save(
        AwaitableTask("e1", "n1", AwaitableKind.EXTERNAL, "api")
    )

    snap = await wm.snapshot("e1")
    assert snap.status is ExecutionStatus.RUNNING
    assert snap.completed_nodes == ["n1"]
    assert len(snap.awaitable_tasks) == 1


async def test_working_memory_load_for_resume():
    ckpt_store = InMemoryCheckpointStore()
    wm = WorkingMemory(checkpoint_store=ckpt_store)

    await ckpt_store.save(Checkpoint("e1", {"n1": "r1"}, resumable=True))
    snap = await wm.load_for_resume("e1")
    assert snap is not None
    assert snap.checkpoint is not None


async def test_working_memory_load_for_resume_none():
    wm = WorkingMemory()
    assert await wm.load_for_resume("nonexistent") is None


async def test_working_memory_save():
    ckpt_store = InMemoryCheckpointStore()
    status_store = InMemoryExecutionStatusStore()
    wm = WorkingMemory(ckpt_store, status_store)

    await wm.save_checkpoint(Checkpoint("e1", {"n1": "r1"}))
    await wm.save_status(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING))

    snap = await wm.snapshot("e1")
    assert snap.completed_nodes == ["n1"]
    assert snap.status is ExecutionStatus.RUNNING


async def test_working_memory_no_stores():
    wm = WorkingMemory()
    snap = await wm.snapshot("e1")
    assert snap.status is None
    assert snap.checkpoint is None


# ===== SemanticMemory =====

class _MockSharedStore(SharedSemanticStore):
    async def recall(self, request):
        return [SemanticRecallResult(content="shared知识", score=0.9)]


class _MockUserStore(UserSemanticStore):
    def __init__(self):
        self._facts: dict[str, list[str]] = {}

    async def recall(self, request):
        return [SemanticRecallResult(content="用户事实", score=0.8)]

    async def remember(self, user_id, content, importance=0.5, metadata=None):
        self._facts.setdefault(user_id, []).append(content)

    async def forget(self, user_id, content):
        if user_id in self._facts and content in self._facts[user_id]:
            self._facts[user_id].remove(content)
            return True
        return False


async def test_semantic_recall_both():
    sem = SemanticMemory(_MockSharedStore(), _MockUserStore())
    results = await sem.recall(
        SemanticRecallRequest(query="展会", user_id="u1", top_k=10)
    )
    assert len(results) == 2
    sources = {r.source for r in results}
    assert sources == {"shared", "user"}
    # 按 score 降序
    assert results[0].score >= results[1].score


async def test_semantic_recall_shared_only():
    sem = SemanticMemory(_MockSharedStore())
    results = await sem.recall(SemanticRecallRequest(query="展会"))
    assert len(results) == 1
    assert results[0].source == "shared"


async def test_semantic_recall_user_only():
    sem = SemanticMemory(user_store=_MockUserStore())
    results = await sem.recall(
        SemanticRecallRequest(query="偏好", user_id="u1")
    )
    assert len(results) == 1
    assert results[0].source == "user"


async def test_semantic_remember_fact():
    user_store = _MockUserStore()
    sem = SemanticMemory(user_store=user_store)
    await sem.remember_fact("u1", "preferred_city=Shanghai", importance=0.8)
    assert "preferred_city=Shanghai" in user_store._facts["u1"]


async def test_semantic_forget_fact():
    user_store = _MockUserStore()
    sem = SemanticMemory(user_store=user_store)
    await sem.remember_fact("u1", "fact1")
    assert await sem.forget_fact("u1", "fact1") is True
    assert await sem.forget_fact("u1", "nonexistent") is False


# ===== MemoryCategory / MemoryRetriever / ContextSelector =====

def test_memory_category_values():
    assert MemoryCategory.WORKING.value == "working"
    assert MemoryCategory.EPISODIC.value == "episodic"
    assert MemoryCategory.SEMANTIC.value == "semantic"
    assert MemoryCategory.PROCEDURAL.value == "procedural"


async def test_memory_retriever_semantic():
    sem = SemanticMemory(_MockSharedStore())
    retriever = MemoryRetriever(semantic=sem)
    results = await retriever.recall(
        MemoryRecallRequest(
            query="展会",
            categories={MemoryCategory.SEMANTIC},
        )
    )
    assert len(results) == 1
    assert results[0].category is MemoryCategory.SEMANTIC


async def test_memory_retriever_working():
    ckpt_store = InMemoryCheckpointStore()
    wm = WorkingMemory(checkpoint_store=ckpt_store)
    await ckpt_store.save(Checkpoint("e1", {"n1": "r1"}))

    retriever = MemoryRetriever(working=wm)
    results = await retriever.recall(
        MemoryRecallRequest(
            query="状态",
            execution_id="e1",
            categories={MemoryCategory.WORKING},
        )
    )
    assert len(results) == 1
    assert results[0].category is MemoryCategory.WORKING


async def test_memory_retriever_no_retriever():
    retriever = MemoryRetriever()
    results = await retriever.recall(
        MemoryRecallRequest(query="test", categories={MemoryCategory.SEMANTIC})
    )
    assert results == []


def test_context_selector_qa():
    selector = ContextSelector()
    sel = selector.select(task_type="qa")
    assert MemoryCategory.SEMANTIC in sel.categories
    assert MemoryCategory.EPISODIC in sel.categories
    assert MemoryCategory.WORKING not in sel.categories


def test_context_selector_execute():
    selector = ContextSelector()
    sel = selector.select(task_type="execute")
    assert MemoryCategory.WORKING in sel.categories
    assert MemoryCategory.PROCEDURAL in sel.categories


def test_context_selector_analyze():
    selector = ContextSelector()
    sel = selector.select(task_type="analyze")
    assert len(sel.categories) == 3


def test_context_selector_approve():
    selector = ContextSelector()
    sel = selector.select(task_type="approve")
    assert sel.categories == {MemoryCategory.WORKING}


def test_context_selector_default():
    selector = ContextSelector()
    sel = selector.select()
    assert MemoryCategory.SEMANTIC in sel.categories


def test_context_selector_unknown():
    selector = ContextSelector()
    sel = selector.select(task_type="unknown_type")
    assert MemoryCategory.SEMANTIC in sel.categories
