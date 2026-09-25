"""Reflection 机制测试。"""

import time

from agent_runtime.episodic_memory import Episode, EpisodeOutcome
from agent_runtime.reflection import Insight, ReflectionEngine


def _ep(eid: str, task: str, outcome: EpisodeOutcome, age: float = 0.0) -> Episode:
    return Episode(
        episode_id=eid,
        execution_id="exec",
        task_summary=task,
        outcome=outcome,
        importance=0.7,
        created_at=time.time() - age,
    )


async def test_reflection_empty_episodes():
    engine = ReflectionEngine()
    insights = await engine.reflect([])
    assert insights == []


async def test_reflection_statistical_high_success():
    engine = ReflectionEngine()
    episodes = [
        _ep("e1", "招商分析", EpisodeOutcome.SUCCESS),
        _ep("e2", "招商分析", EpisodeOutcome.SUCCESS),
        _ep("e3", "招商分析", EpisodeOutcome.SUCCESS),
        _ep("e4", "招商分析", EpisodeOutcome.FAILURE),
    ]
    insights = await engine.reflect(episodes)
    assert len(insights) >= 1
    assert insights[0].confidence >= 0.6
    assert "招商分析" in insights[0].question


async def test_reflection_statistical_low_success():
    engine = ReflectionEngine()
    episodes = [
        _ep("e1", "失败任务", EpisodeOutcome.FAILURE),
        _ep("e2", "失败任务", EpisodeOutcome.FAILURE),
        _ep("e3", "失败任务", EpisodeOutcome.FAILURE),
        _ep("e4", "失败任务", EpisodeOutcome.SUCCESS),
    ]
    insights = await engine.reflect(episodes)
    assert len(insights) >= 1
    assert insights[0].confidence <= 0.5


async def test_reflection_statistical_skips_single_episode():
    engine = ReflectionEngine()
    episodes = [_ep("e1", "唯一任务", EpisodeOutcome.SUCCESS)]
    insights = await engine.reflect(episodes)
    assert len(insights) == 0


async def test_reflection_with_mock_llm():
    class _MockLLM:
        async def chat(self, prompt: str) -> str:
            if "Generate" in prompt:
                return "什么是招商分析的最佳模式？\n如何优化搜索步骤？\n什么是常见错误？"
            return f"基于证据的回答（prompt length={len(prompt)}）"

    engine = ReflectionEngine(llm=_MockLLM(), num_questions=3)
    episodes = [
        _ep("e1", "招商分析", EpisodeOutcome.SUCCESS),
        _ep("e2", "招商分析", EpisodeOutcome.SUCCESS),
    ]
    insights = await engine.reflect(episodes)
    assert len(insights) == 3
    assert all(isinstance(i, Insight) for i in insights)
    assert all(i.evidence_count == 2 for i in insights)


def test_insight_to_dict():
    insight = Insight(question="Q", answer="A", evidence_count=5, confidence=0.9)
    d = insight.to_dict()
    assert d["question"] == "Q"
    assert d["answer"] == "A"
    assert d["evidence_count"] == 5
    assert d["confidence"] == 0.9
