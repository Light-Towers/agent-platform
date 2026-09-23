"""高级 Memory 功能测试：recency 衰减 + 三因子加权 + 幻觉检测 + 衰减管理 + 种子记忆 + Embedding。"""

import time

from agent_runtime.embedding_recall import EmbeddingRecall
from agent_runtime.episodic_memory import (
    Episode,
    EpisodeOutcome,
    EpisodicExtractor,
    EpisodicMemory,
    InMemoryEpisodicStore,
)
from agent_runtime.memory_decay import MemoryDecayManager
from agent_runtime.memory_recall import (
    bigrams,
    jaccard_similarity,
    recency_score,
    text_similarity,
    three_factor_score,
)
from agent_runtime.memory_seed import MemorySeeder
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep

# ===== recency 衰减 =====

def test_recency_score_fresh():
    now = time.time()
    score = recency_score(now, now=now)
    assert abs(score - 1.0) < 0.001


def test_recency_score_old():
    now = time.time()
    old = now - 1000
    score = recency_score(old, now=now)
    assert 0 < score < 0.01


def test_recency_score_decay():
    now = time.time()
    s1 = recency_score(now - 10, now=now, decay=0.99)
    s2 = recency_score(now - 20, now=now, decay=0.99)
    assert s1 > s2


# ===== 三因子加权 =====

def test_three_factor_score():
    now = time.time()
    score = three_factor_score(
        relevance=0.8, importance=0.9, created_at=now, now=now
    )
    assert 0 < score <= 1.0


def test_three_factor_old_episode_scores_lower():
    now = time.time()
    fresh = three_factor_score(0.8, 0.9, now, now=now)
    old = three_factor_score(0.8, 0.9, now - 1000, now=now)
    assert fresh > old


# ===== bigram Jaccard =====

def test_bigrams():
    assert bigrams("招商") == {"招商"}
    assert bigrams("招商分析") == {"招商", "商分", "分析"}


def test_jaccard_similarity():
    assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0
    assert jaccard_similarity({"a", "b"}, {"a", "c"}) == 1 / 3


def test_text_similarity_word_order():
    sim1 = text_similarity("招商分析", "招商分析")
    sim2 = text_similarity("分析招商", "招商分析")
    assert sim1 == 1.0
    assert sim2 > 0


# ===== 幻觉检测 =====

def test_detect_hallucination_true():
    traj = TrajectoryRecord(
        execution_id="e1",
        plan={"task": "test"},
        steps=[
            TrajectoryStep(name="search", result="ok"),
            TrajectoryStep(name="search", result="ok"),
            TrajectoryStep(name="search", result="ok"),
        ],
    )
    extractor = EpisodicExtractor()
    assert extractor.detect_hallucination(traj) is True


def test_detect_hallucination_false():
    traj = TrajectoryRecord(
        execution_id="e1",
        plan={"task": "test"},
        steps=[
            TrajectoryStep(name="search", result="a"),
            TrajectoryStep(name="analyze", result="b"),
            TrajectoryStep(name="render", result="c"),
        ],
    )
    extractor = EpisodicExtractor()
    assert extractor.detect_hallucination(traj) is False


def test_extract_with_hallucination_marks_failure():
    traj = TrajectoryRecord(
        execution_id="e1",
        plan={"task": "test"},
        steps=[
            TrajectoryStep(name="search", result="ok"),
            TrajectoryStep(name="search", result="ok"),
            TrajectoryStep(name="search", result="ok"),
        ],
    )
    extractor = EpisodicExtractor()
    ep = extractor.extract(traj)
    assert ep.outcome is EpisodeOutcome.FAILURE
    assert ep.importance == 0.3
    assert any("幻觉" in lesson for lesson in ep.lessons)


# ===== MemoryDecayManager =====

async def test_memory_decay_cleanup_expired():
    store = InMemoryEpisodicStore()
    old_ep = Episode(
        episode_id="old",
        execution_id="e1",
        task_summary="old task",
        created_at=time.time() - 999999,
    )
    new_ep = Episode(
        episode_id="new",
        execution_id="e2",
        task_summary="new task",
        created_at=time.time(),
    )
    await store.save(old_ep)
    await store.save(new_ep)

    decay = MemoryDecayManager(store, max_age_seconds=100, max_size=10000)
    expired, evicted = await decay.cleanup()
    assert expired == 1
    assert evicted == 0
    assert await store.get("old") is None
    assert await store.get("new") is not None


async def test_memory_decay_cleanup_evict_low_importance():
    store = InMemoryEpisodicStore()
    for i in range(5):
        await store.save(Episode(
            episode_id=f"ep{i}",
            execution_id="e1",
            task_summary=f"task{i}",
            importance=0.1 * i,
            created_at=time.time(),
        ))

    decay = MemoryDecayManager(store, max_age_seconds=999999, max_size=3)
    expired, evicted = await decay.cleanup()
    assert expired == 0
    assert evicted == 2
    remaining = await store.list_all()
    assert len(remaining) == 3


# ===== MemorySeeder =====

async def test_memory_seeder_seeds_new_episodes():
    store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(store)
    seeder = MemorySeeder(ep_mem)

    count = await seeder.seed([
        Episode(episode_id="seed1", execution_id="s", task_summary="种子1"),
        Episode(episode_id="seed2", execution_id="s", task_summary="种子2"),
    ])
    assert count == 2
    all_eps = await store.list_all()
    assert len(all_eps) == 2


async def test_memory_seeder_skips_existing():
    store = InMemoryEpisodicStore()
    ep_mem = EpisodicMemory(store)
    seeder = MemorySeeder(ep_mem)

    await seeder.seed([Episode(episode_id="seed1", execution_id="s", task_summary="种子1")])
    count = await seeder.seed([Episode(episode_id="seed1", execution_id="s", task_summary="种子1")])
    assert count == 0


# ===== EmbeddingRecall =====

async def test_embedding_recall_fallback_to_bigram():
    recall = EmbeddingRecall()
    sim = await recall.similarity("招商分析", "招商分析")
    assert sim == 1.0


async def test_embedding_recall_hash_embed():
    recall = EmbeddingRecall(dim=64)
    vec = await recall.embed("test text")
    assert len(vec) == 64
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 0.01


async def test_embedding_recall_with_mock_embed_fn():
    async def mock_embed(text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]

    recall = EmbeddingRecall(embed_fn=mock_embed)
    sim = await recall.similarity("abc", "ab")
    assert 0 < sim <= 1.0
