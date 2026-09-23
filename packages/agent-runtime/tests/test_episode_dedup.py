"""EpisodeDeduplicator 单测：去重/压缩。"""


from agent_runtime.episode_dedup import EpisodeDeduplicator
from agent_runtime.episodic_memory import Episode, EpisodeOutcome


def _ep(
    eid: str = "e1",
    task: str = "招商分析",
    outcome: EpisodeOutcome = EpisodeOutcome.SUCCESS,
    importance: float = 0.7,
    lessons: list[str] | None = None,
    skill_names: list[str] | None = None,
    tokens: int = 100,
    cost: float = 0.01,
    duration: float = 1.0,
) -> Episode:
    return Episode(
        episode_id=eid,
        execution_id="exec1",
        task_summary=task,
        outcome=outcome,
        importance=importance,
        lessons=lessons or [],
        skill_names=skill_names or [],
        total_tokens=tokens,
        total_cost=cost,
        duration=duration,
    )


def test_dedup_no_duplicates():
    eps = [_ep("e1"), _ep("e2", task="SQL查询")]
    dedup = EpisodeDeduplicator()
    result, merged = dedup.deduplicate(eps)
    assert len(result) == 2
    assert merged == 0


def test_dedup_merges_same_task_and_outcome():
    eps = [_ep("e1"), _ep("e2"), _ep("e3")]
    dedup = EpisodeDeduplicator()
    result, merged = dedup.deduplicate(eps)
    assert len(result) == 1
    assert merged == 2


def test_dedup_preserves_highest_importance():
    eps = [_ep("e1", importance=0.5), _ep("e2", importance=0.9), _ep("e3", importance=0.3)]
    dedup = EpisodeDeduplicator()
    result, _ = dedup.deduplicate(eps)
    assert result[0].importance == 0.9


def test_dedup_merges_lessons_deduplicated():
    eps = [
        _ep("e1", lessons=["a", "b"]),
        _ep("e2", lessons=["b", "c"]),
    ]
    dedup = EpisodeDeduplicator()
    result, _ = dedup.deduplicate(eps)
    assert set(result[0].lessons) == {"a", "b", "c"}
    assert len(result[0].lessons) == 3


def test_dedup_merges_skill_names_deduplicated():
    eps = [
        _ep("e1", skill_names=["search", "analyze"]),
        _ep("e2", skill_names=["analyze", "render"]),
    ]
    dedup = EpisodeDeduplicator()
    result, _ = dedup.deduplicate(eps)
    assert set(result[0].skill_names) == {"search", "analyze", "render"}


def test_dedup_accumulates_costs():
    eps = [
        _ep("e1", tokens=100, cost=0.01, duration=1.0),
        _ep("e2", tokens=200, cost=0.02, duration=2.0),
    ]
    dedup = EpisodeDeduplicator()
    result, _ = dedup.deduplicate(eps)
    assert result[0].total_tokens == 300
    assert result[0].total_cost == 0.03
    assert result[0].duration == 3.0


def test_dedup_different_outcomes_not_merged():
    eps = [
        _ep("e1", outcome=EpisodeOutcome.SUCCESS),
        _ep("e2", outcome=EpisodeOutcome.FAILURE),
    ]
    dedup = EpisodeDeduplicator()
    result, merged = dedup.deduplicate(eps)
    assert len(result) == 2
    assert merged == 0


def test_dedup_records_dedup_count():
    eps = [_ep("e1"), _ep("e2"), _ep("e3")]
    dedup = EpisodeDeduplicator()
    result, _ = dedup.deduplicate(eps)
    assert result[0].metadata.get("dedup_count") == 2


def test_dedup_empty_list():
    dedup = EpisodeDeduplicator()
    result, merged = dedup.deduplicate([])
    assert result == []
    assert merged == 0
