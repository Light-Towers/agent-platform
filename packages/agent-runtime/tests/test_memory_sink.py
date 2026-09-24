"""memory_sink 单测：自动沉淀管道 + 反馈闭环。

验证：
- EpisodicSink：执行后自动沉淀 Episode；
- ProceduralSink：定期挖掘候选 Skill → 持久化；
- SkillUsageTracker：使用效果 → lifecycle 升降级；
- 集成：_persist_trajectory 后自动触发 hooks。
"""


from agent_runtime.episodic_memory import (
    EpisodicMemory,
    InMemoryEpisodicStore,
)
from agent_runtime.memory_sink import (
    EpisodicSink,
    ProceduralSink,
    SkillUsageTracker,
)
from agent_runtime.planner.execution_graph import _persist_trajectory
from agent_runtime.planner.protocol import Plan, PlannerRuntime
from agent_runtime.procedural_memory import (
    InMemoryProceduralStore,
    ProceduralEntry,
)
from agent_runtime.skills.registry import SkillRegistry
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep


def _trajectory(
    execution_id: str = "e1",
    steps: list[TrajectoryStep] | None = None,
    task: str = "招商分析",
) -> TrajectoryRecord:
    return TrajectoryRecord(
        execution_id=execution_id,
        planner="agentic",
        plan={"task": task},
        steps=steps or [
            TrajectoryStep(name="search", latency=1.0, tokens=100),
            TrajectoryStep(name="analyze", latency=2.0, tokens=200),
        ],
    )


# ===== EpisodicSink =====

async def test_episodic_sink_saves_episode():
    store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(store)
    sink = EpisodicSink(ep_mem)

    traj = _trajectory()
    await sink(traj, runtime=None)

    all_eps = await store.list_all()
    assert len(all_eps) == 1
    assert all_eps[0].task_summary == "招商分析"


async def test_episodic_sink_skips_low_steps():
    store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(store)
    sink = EpisodicSink(ep_mem)

    traj = TrajectoryRecord(
        execution_id="e1",
        planner="agentic",
        plan={"task": "简单"},
        steps=[TrajectoryStep(name="only", latency=1.0, tokens=50)],
    )
    await sink(traj, runtime=None)

    all_eps = await store.list_all()
    assert len(all_eps) == 0


# ===== ProceduralSink =====

async def test_procedural_sink_triggers_at_interval():
    ep_store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(ep_store)
    proc_store = InMemoryProceduralStore()

    ep_sink = EpisodicSink(ep_mem)
    proc_sink = ProceduralSink(ep_mem, proc_store, trigger_interval=3)

    for i in range(3):
        traj = _trajectory(execution_id=f"e{i}", task="招商分析")
        await ep_sink(traj, runtime=None)
        await proc_sink(traj, runtime=None)

    entries = await proc_store.list_all()
    assert len(entries) >= 1
    assert entries[0].lifecycle == "draft"


async def test_procedural_sink_not_triggered_before_interval():
    ep_store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(ep_store)
    proc_store = InMemoryProceduralStore()

    ep_sink = EpisodicSink(ep_mem)
    proc_sink = ProceduralSink(ep_mem, proc_store, trigger_interval=5)

    for i in range(3):
        traj = _trajectory(execution_id=f"e{i}")
        await ep_sink(traj, runtime=None)
        await proc_sink(traj, runtime=None)

    entries = await proc_store.list_all()
    assert len(entries) == 0


# ===== SkillUsageTracker =====

async def test_skill_usage_tracker_record_and_stats():
    proc_store = InMemoryProceduralStore()
    tracker = SkillUsageTracker(proc_store)

    tracker.record_use("search", "1.0", success=True)
    tracker.record_use("search", "1.0", success=False)
    tracker.record_use("search", "1.0", success=True)

    stats = tracker.get_stats("search", "1.0")
    assert stats is not None
    assert stats["success"] == 2
    assert stats["total"] == 3


async def test_skill_usage_tracker_promote_draft_to_stable():
    proc_store = InMemoryProceduralStore()

    await proc_store.save(ProceduralEntry(
        name="search", version="1.0", kind="function",
        description="", lifecycle="draft",
    ))

    tracker = SkillUsageTracker(proc_store, promote_threshold=0.8, min_uses=5)

    for _ in range(5):
        tracker.record_use("search", "1.0", success=True)

    new_lc = await tracker.check_and_adjust("search", "1.0")
    assert new_lc == "stable"

    entry = await proc_store.load("search", "1.0")
    assert entry.lifecycle == "stable"


async def test_skill_usage_tracker_demote_stable_to_deprecated():
    proc_store = InMemoryProceduralStore()

    await proc_store.save(ProceduralEntry(
        name="search", version="1.0", kind="function",
        description="", lifecycle="stable",
    ))

    tracker = SkillUsageTracker(proc_store, demote_threshold=0.3, min_uses=5)

    for _ in range(4):
        tracker.record_use("search", "1.0", success=False)
    tracker.record_use("search", "1.0", success=True)

    new_lc = await tracker.check_and_adjust("search", "1.0")
    assert new_lc == "deprecated"

    entry = await proc_store.load("search", "1.0")
    assert entry.lifecycle == "deprecated"


async def test_skill_usage_tracker_no_adjust_below_min_uses():
    proc_store = InMemoryProceduralStore()

    await proc_store.save(ProceduralEntry(
        name="search", version="1.0", kind="function",
        description="", lifecycle="draft",
    ))

    tracker = SkillUsageTracker(proc_store, min_uses=10)

    for _ in range(5):
        tracker.record_use("search", "1.0", success=True)

    new_lc = await tracker.check_and_adjust("search", "1.0")
    assert new_lc is None


async def test_skill_usage_tracker_no_adjust_when_rate_in_range():
    proc_store = InMemoryProceduralStore()

    await proc_store.save(ProceduralEntry(
        name="search", version="1.0", kind="function",
        description="", lifecycle="stable",
    ))

    tracker = SkillUsageTracker(proc_store, promote_threshold=0.8, demote_threshold=0.3, min_uses=5)

    for _ in range(3):
        tracker.record_use("search", "1.0", success=True)
    for _ in range(2):
        tracker.record_use("search", "1.0", success=False)

    new_lc = await tracker.check_and_adjust("search", "1.0")
    assert new_lc is None


# ===== 集成：_persist_trajectory 触发 hooks =====

async def test_post_execution_hook_triggered():
    hook_calls: list[TrajectoryRecord] = []

    async def mock_hook(trajectory: TrajectoryRecord, runtime):
        hook_calls.append(trajectory)

    runtime = PlannerRuntime(
        SkillRegistry(),
        post_execution_hooks=[mock_hook],
    )
    plan = Plan(route="test", planner_name="test")

    class _MockExecCtx:
        execution_id = "e1"
        steps = [TrajectoryStep(name="s1", latency=1.0, tokens=10)]
        tokens_used = 10
        cost_used = 0.001
        metadata = {}

    class _MockAgentCtx:
        def snapshot(self):
            return {}

    await _persist_trajectory(runtime, plan, _MockAgentCtx(), _MockExecCtx())

    assert len(hook_calls) == 1
    assert hook_calls[0].execution_id == "e1"


async def test_post_execution_hook_failure_does_not_propagate():
    async def bad_hook(trajectory, runtime):
        raise RuntimeError("hook failed")

    runtime = PlannerRuntime(
        SkillRegistry(),
        post_execution_hooks=[bad_hook],
    )
    plan = Plan(route="test", planner_name="test")

    class _MockExecCtx:
        execution_id = "e1"
        steps = []
        tokens_used = 0
        cost_used = 0.0
        metadata = {}

    class _MockAgentCtx:
        def snapshot(self):
            return {}

    await _persist_trajectory(runtime, plan, _MockAgentCtx(), _MockExecCtx())
    assert runtime.last_trajectory is not None


async def test_episodic_sink_integration_with_persist_trajectory():
    """端到端：_persist_trajectory → EpisodicSink → Episode 沉淀。"""
    ep_store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(ep_store)
    sink = EpisodicSink(ep_mem)

    runtime = PlannerRuntime(
        SkillRegistry(),
        post_execution_hooks=[sink],
    )
    plan = Plan(route="test", planner_name="test")

    class _MockExecCtx:
        execution_id = "e1"
        steps = [
            TrajectoryStep(name="search", latency=1.0, tokens=100),
            TrajectoryStep(name="analyze", latency=2.0, tokens=200),
        ]
        tokens_used = 300
        cost_used = 0.03
        metadata = {}

    class _MockAgentCtx:
        def snapshot(self):
            return {}

    await _persist_trajectory(runtime, plan, _MockAgentCtx(), _MockExecCtx())

    all_eps = await ep_store.list_all()
    assert len(all_eps) == 1
    assert all_eps[0].execution_id == "e1"
