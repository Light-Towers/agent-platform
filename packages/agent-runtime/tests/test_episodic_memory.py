"""四类 Memory 阶段 2 单测：Episodic Memory 沉淀管道。

验证：
- Episode：数据结构 / content_for_recall；
- EpisodicExtractor：should_extract / extract（成功/失败/部分成功）；
- InMemoryEpisodicStore：save / recall / get / list_by_execution；
- EpisodicMemory：remember / recall 端到端。
"""


from agent_runtime.episodic_memory import (
    Episode,
    EpisodeOutcome,
    EpisodicExtractor,
    EpisodicMemory,
    InMemoryEpisodicStore,
)
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep


def _trajectory(
    execution_id: str = "e1",
    steps: list[TrajectoryStep] | None = None,
    plan: dict | None = None,
) -> TrajectoryRecord:
    return TrajectoryRecord(
        execution_id=execution_id,
        planner="agentic",
        plan=plan or {"task": "会展招商分析"},
        steps=steps or [],
    )


def _step(name: str, error: str | None = None, latency: float = 1.0) -> TrajectoryStep:
    return TrajectoryStep(name=name, error=error, latency=latency, tokens=100)


# ===== Episode =====

def test_episode_content_for_recall():
    ep = Episode(
        execution_id="e1",
        task_summary="招商分析",
        key_steps=["查询", "分析", "报告"],
        lessons=["注意字段名"],
    )
    content = ep.content_for_recall()
    assert "招商分析" in content
    assert "查询" in content
    assert "注意字段名" in content


def test_episode_to_dict():
    ep = Episode(execution_id="e1", task_summary="test", outcome=EpisodeOutcome.SUCCESS)
    d = ep.to_dict()
    assert d["outcome"] == "success"
    assert d["execution_id"] == "e1"


# ===== EpisodicExtractor =====

def test_extractor_should_extract_min_steps():
    extractor = EpisodicExtractor(min_steps=2)
    traj = _trajectory(steps=[_step("s1")])
    assert not extractor.should_extract(traj)

    traj = _trajectory(steps=[_step("s1"), _step("s2")])
    assert extractor.should_extract(traj)


def test_extractor_success():
    extractor = EpisodicExtractor()
    traj = _trajectory(
        steps=[_step("query"), _step("analyze"), _step("report")],
    )
    ep = extractor.extract(traj)
    assert ep.outcome is EpisodeOutcome.SUCCESS
    assert ep.importance == 0.7
    assert len(ep.key_steps) == 3
    assert ep.lessons == []


def test_extractor_partial_success():
    extractor = EpisodicExtractor()
    traj = _trajectory(
        steps=[
            _step("query", error="字段错误"),
            _step("query"),
            _step("report"),
        ],
    )
    ep = extractor.extract(traj)
    assert ep.outcome is EpisodeOutcome.PARTIAL
    assert ep.importance == 0.9
    assert len(ep.lessons) == 1


def test_extractor_failure():
    extractor = EpisodicExtractor()
    traj = _trajectory(
        steps=[_step("query"), _step("analyze", error="超时")],
    )
    ep = extractor.extract(traj)
    assert ep.outcome is EpisodeOutcome.FAILURE
    assert ep.importance == 0.6
    assert len(ep.lessons) == 1


def test_extractor_skill_names():
    extractor = EpisodicExtractor()
    traj = _trajectory(
        steps=[_step("search"), _step("analyze"), _step("search")],
    )
    ep = extractor.extract(traj)
    assert set(ep.skill_names) == {"search", "analyze"}


# ===== InMemoryEpisodicStore =====

async def test_store_save_and_get():
    store = InMemoryEpisodicStore()
    ep = Episode(execution_id="e1", task_summary="test")
    await store.save(ep)
    loaded = await store.get(ep.episode_id)
    assert loaded is not None
    assert loaded.task_summary == "test"


async def test_store_recall():
    store = InMemoryEpisodicStore()
    await store.save(Episode(execution_id="e1", task_summary="会展招商分析", importance=0.9))
    await store.save(Episode(execution_id="e2", task_summary="SQL查询", importance=0.5))

    results = await store.recall("会展")
    assert len(results) == 1
    assert results[0].task_summary == "会展招商分析"


async def test_store_list_by_execution():
    store = InMemoryEpisodicStore()
    await store.save(Episode(execution_id="e1", task_summary="test1"))
    await store.save(Episode(execution_id="e1", task_summary="test2"))
    await store.save(Episode(execution_id="e2", task_summary="test3"))

    results = await store.list_by_execution("e1")
    assert len(results) == 2


# ===== EpisodicMemory 端到端 =====

async def test_episodic_remember_and_recall():
    ep_mem = EpisodicMemory(InMemoryEpisodicStore())

    traj = _trajectory(
        execution_id="e1",
        steps=[_step("query"), _step("analyze"), _step("report")],
    )
    episode = await ep_mem.remember(traj)
    assert episode is not None
    assert episode.outcome is EpisodeOutcome.SUCCESS

    results = await ep_mem.recall("会展招商分析")
    assert len(results) == 1
    assert results[0].execution_id == "e1"


async def test_episodic_remember_skips_simple():
    ep_mem = EpisodicMemory(InMemoryEpisodicStore())

    traj = _trajectory(steps=[_step("s1")])  # 只有 1 步
    episode = await ep_mem.remember(traj)
    assert episode is None  # 太简单，不值得沉淀


async def test_episodic_remember_partial_with_lessons():
    ep_mem = EpisodicMemory(InMemoryEpisodicStore())

    traj = _trajectory(
        execution_id="e1",
        steps=[
            _step("query", error="字段不存在"),
            _step("query"),
            _step("report"),
        ],
    )
    episode = await ep_mem.remember(traj)
    assert episode is not None
    assert episode.outcome is EpisodeOutcome.PARTIAL
    assert len(episode.lessons) == 1

    # 召回时能找到
    results = await ep_mem.recall("会展")
    assert len(results) == 1
    assert results[0].importance == 0.9


async def test_episodic_remember_failure():
    ep_mem = EpisodicMemory(InMemoryEpisodicStore())

    traj = _trajectory(
        execution_id="e1",
        steps=[_step("query"), _step("analyze", error="超时")],
    )
    episode = await ep_mem.remember(traj)
    assert episode.outcome is EpisodeOutcome.FAILURE
    assert episode.importance == 0.6
