"""Reflection 机制：从 Episodic Memory 生成高层抽象。

Generative Agents 论文的方法：
1. 取最近 N 条 Episode
2. LLM 生成 K 个最突出的高层问题
3. LLM 回答这些问题
4. 答案作为新的 Insight 存储（比单条 Episode 更抽象）

无 LLM 时退化为统计反思：按 task_summary 分组统计成功/失败率。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.episodic_memory import Episode, EpisodeOutcome

logger = logging.getLogger(__name__)


@dataclass
class Insight:
    """反思洞察：从多次经历中提炼的高层抽象。"""

    question: str
    answer: str
    evidence_count: int = 0
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "evidence_count": self.evidence_count,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


class ReflectionEngine:
    """从 Episodic Memory 生成高层抽象（Reflection）。

    用法：
    ```
    engine = ReflectionEngine(llm=my_llm)
    insights = await engine.reflect(all_episodes)
    # 或无 LLM → 统计反思
    engine = ReflectionEngine()
    insights = await engine.reflect(all_episodes)
    ```
    """

    def __init__(
        self,
        llm: Any = None,
        window: int = 100,
        num_questions: int = 3,
    ) -> None:
        self._llm = llm
        self._window = window
        self._num_questions = num_questions

    async def reflect(self, episodes: list[Episode]) -> list[Insight]:
        """从 Episode 列表生成高层 Insight。"""
        if not episodes:
            return []

        recent = sorted(episodes, key=lambda e: e.created_at, reverse=True)[
            : self._window
        ]

        if self._llm is not None:
            return await self._llm_reflect(recent)
        return self._statistical_reflect(recent)

    async def _llm_reflect(self, episodes: list[Episode]) -> list[Insight]:
        """LLM 驱动的反思：生成问题 → 回答 → Insight。"""
        summaries = [e.task_summary for e in episodes]
        questions = await self._generate_questions(summaries)

        insights = []
        for q in questions:
            answer = await self._answer_question(q, episodes)
            insights.append(
                Insight(
                    question=q,
                    answer=answer,
                    evidence_count=len(episodes),
                    confidence=0.8,
                )
            )
        return insights

    async def _generate_questions(self, summaries: list[str]) -> list[str]:
        """用 LLM 生成高层问题。"""
        prompt = (
            f"Given these task summaries: {summaries[:20]}\n"
            f"Generate {self._num_questions} high-level questions "
            "that capture the most salient patterns."
        )
        resp = await self._llm.chat(prompt)
        return [
            line.strip() for line in resp.split("\n") if line.strip()
        ][: self._num_questions]

    async def _answer_question(self, question: str, episodes: list[Episode]) -> str:
        """用 LLM 回答问题。"""
        context = "\n".join(
            f"- {e.task_summary} ({e.outcome.value})" for e in episodes[:20]
        )
        prompt = f"Question: {question}\nEvidence:\n{context}\nAnswer:"
        return await self._llm.chat(prompt)

    def _statistical_reflect(self, episodes: list[Episode]) -> list[Insight]:
        """无 LLM 时的统计反思：按 task_summary 分组统计。"""
        by_task: dict[str, list[Episode]] = {}
        for ep in episodes:
            by_task.setdefault(ep.task_summary, []).append(ep)

        insights: list[Insight] = []
        for task, task_eps in by_task.items():
            success_count = sum(
                1 for e in task_eps if e.outcome == EpisodeOutcome.SUCCESS
            )
            total = len(task_eps)
            if total < 2:
                continue
            rate = success_count / total

            question = f"任务 '{task}' 的成功模式是什么？"
            if rate >= 0.8:
                answer = f"高成功率 ({rate:.0%})，{success_count}/{total} 次成功。可靠模式。"
                confidence = 0.9
            elif rate >= 0.5:
                answer = f"中等成功率 ({rate:.0%})，{success_count}/{total} 次成功。需优化。"
                confidence = 0.6
            else:
                answer = f"低成功率 ({rate:.0%})，{success_count}/{total} 次成功。应避免。"
                confidence = 0.4

            insights.append(
                Insight(
                    question=question,
                    answer=answer,
                    evidence_count=total,
                    confidence=confidence,
                )
            )

        insights.sort(key=lambda i: i.confidence, reverse=True)
        return insights[: self._num_questions * 3]


__all__ = ["Insight", "ReflectionEngine"]
