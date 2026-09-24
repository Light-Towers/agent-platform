"""Memory 闭环端到端测试：验证"越用越好"完整链路。

场景：
1. 执行 N 次相同任务 → EpisodicSink 自动沉淀 Episode
2. ProceduralSink 定期挖掘候选 Skill → 持久化为 draft
3. SkillUsageTracker 记录使用效果 → draft 升级为 stable
4. 下次相同任务 → ProceduralMemory.recall 召回已学会的 Skill
5. EpisodeDeduplicator 压缩重复 Episode
"""


from agent_runtime.episode_dedup import EpisodeDeduplicator
from agent_runtime.episodic_memory import (
    EpisodicMemory,
    InMemoryEpisodicStore,
)
from agent_runtime.memory_sink import (
    EpisodicSink,
    ProceduralSink,
    SkillUsageTracker,
)
from agent_runtime.procedural_memory import (
    InMemoryProceduralStore,
    ProceduralMemory,
)
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep


def _trajectory(execution_id: str, task: str = "招商分析") -> TrajectoryRecord:
    return TrajectoryRecord(
        execution_id=execution_id,
        planner="agentic",
        plan={"task": task},
        steps=[
            TrajectoryStep(name="search", latency=1.0, tokens=100),
            TrajectoryStep(name="analyze", latency=2.0, tokens=200),
        ],
    )


async def test_e2e_learning_closed_loop():
    """端到端：多次执行 → 自动沉淀 → 挖掘 Skill → 升级 → 召回。"""

    ep_store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(ep_store)
    proc_store = InMemoryProceduralStore()
    proc_mem = ProceduralMemory(proc_store)

    ep_sink = EpisodicSink(ep_mem)
    proc_sink = ProceduralSink(ep_mem, proc_store, trigger_interval=3)
    tracker = SkillUsageTracker(proc_store, promote_threshold=0.8, min_uses=5)

    # Phase 1: 执行 5 次相同任务，全部成功
    for i in range(5):
        traj = _trajectory(f"e{i}")
        await ep_sink(traj, runtime=None)
        await proc_sink(traj, runtime=None)

    # 验证：5 个 Episode 已沉淀
    all_eps = await ep_store.list_all()
    assert len(all_eps) == 5

    # 验证：候选 Skill 已挖掘（draft）
    all_skills = await proc_store.list_all()
    assert len(all_skills) >= 1
    candidate = all_skills[0]
    assert candidate.lifecycle == "draft"

    # Phase 2: 记录 5 次成功使用
    for _ in range(5):
        tracker.record_use(candidate.name, candidate.version, success=True)

    # 验证：draft → stable
    new_lc = await tracker.check_and_adjust(candidate.name, candidate.version)
    assert new_lc == "stable"

    # Phase 3: 下次相同任务 → 召回已学会的 Skill
    results = await proc_mem.recall("招商分析")
    assert len(results) >= 1
    assert results[0].lifecycle == "stable"

    # Phase 4: 去重压缩
    dedup = EpisodeDeduplicator()
    unique, merged = dedup.deduplicate(all_eps)
    assert len(unique) == 1
    assert merged == 4
    assert unique[0].metadata.get("dedup_count") == 4


async def test_e2e_skill_demotion_on_failures():
    """端到端：Skill 使用效果差 → 降级为 deprecated。"""

    ep_store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(ep_store)
    proc_store = InMemoryProceduralStore()

    ep_sink = EpisodicSink(ep_mem)
    proc_sink = ProceduralSink(ep_mem, proc_store, trigger_interval=3)

    for i in range(3):
        traj = _trajectory(f"e{i}")
        await ep_sink(traj, runtime=None)
        await proc_sink(traj, runtime=None)

    all_skills = await proc_store.list_all()
    assert len(all_skills) >= 1
    candidate = all_skills[0]

    # 手动升级为 stable（模拟通过验证）
    import time

    from agent_runtime.procedural_memory import ProceduralEntry

    await proc_store.save(ProceduralEntry(
        name=candidate.name,
        version=candidate.version,
        kind=candidate.kind,
        description=candidate.description,
        definition=candidate.definition,
        lifecycle="stable",
        created_at=candidate.created_at,
        updated_at=time.time(),
    ))

    # 记录 5 次失败使用
    tracker = SkillUsageTracker(proc_store, demote_threshold=0.3, min_uses=5)
    for _ in range(5):
        tracker.record_use(candidate.name, candidate.version, success=False)

    new_lc = await tracker.check_and_adjust(candidate.name, candidate.version)
    assert new_lc == "deprecated"


async def test_e2e_recall_with_bigram_similarity():
    """验证 bigram Jaccard 召回：词序不同也能匹配。"""
    ep_store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(ep_store)

    from agent_runtime.episodic_memory import Episode, EpisodeOutcome

    await ep_store.save(Episode(
        episode_id="ep1",
        execution_id="e1",
        task_summary="会展招商分析",
        outcome=EpisodeOutcome.SUCCESS,
        importance=0.9,
    ))

    # "分析招商" 与 "会展招商分析" 有 bigram 交集（"招商"、"分析"）
    results = await ep_mem.recall("分析招商")
    assert len(results) >= 1

    # "完全不同" 不应匹配
    results = await ep_mem.recall("量子计算")
    assert len(results) == 0
