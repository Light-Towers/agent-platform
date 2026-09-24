"""Episodic Memory（四类 Memory 阶段 2）：过去发生过什么。

从 TrajectoryRecord（执行轨迹）提取有价值的 Episode，作为 episodic 召回源。

与其他三类 Memory 的区别：
- Working：当前 execution 的实时状态
- Episodic：**过去执行经历**——"以前类似任务是怎么完成的"
- Semantic：业务事实/知识
- Procedural：做事方法/Skill

核心问题：不是每个 Tool Call 都应该记。
```
Trajectory（完整轨迹）
    ↓
EpisodicExtractor.should_extract?
    ↓ 是
摘要 / 压缩 / 重要性判断
    ↓
Episode（有价值的经历摘要）
    ↓
EpisodicStore（召回源）
```
"""

from __future__ import annotations

import abc
import copy
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_runtime.memory_recall import text_similarity, three_factor_score
from agent_runtime.trajectory.models import TrajectoryRecord

logger = logging.getLogger(__name__)


class EpisodeOutcome(str, Enum):
    """执行结果。"""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"  # 部分成功


_OUTCOME_WEIGHT: dict[EpisodeOutcome, float] = {
    EpisodeOutcome.SUCCESS: 1.0,
    EpisodeOutcome.PARTIAL: 0.7,
    EpisodeOutcome.FAILURE: 0.5,
}


@dataclass
class Episode:
    """一次执行经历的摘要（从 TrajectoryRecord 提取）。

    不是完整轨迹（那是 TrajectoryRecord 的职责），而是**有价值的摘要**——
    供下次类似任务召回参考。
    """

    episode_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    execution_id: str = ""
    task_summary: str = ""  # 任务摘要（如"会展招商分析"）
    outcome: EpisodeOutcome = EpisodeOutcome.SUCCESS
    key_steps: list[str] = field(default_factory=list)  # 关键步骤摘要
    lessons: list[str] = field(default_factory=list)  # 经验教训
    skill_names: list[str] = field(default_factory=list)  # 涉及的 Skill
    total_tokens: int = 0
    total_cost: float = 0.0
    duration: float = 0.0
    importance: float = 0.5  # 重要性（0~1）
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "execution_id": self.execution_id,
            "task_summary": self.task_summary,
            "outcome": self.outcome.value,
            "key_steps": self.key_steps,
            "lessons": self.lessons,
            "skill_names": self.skill_names,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "duration": self.duration,
            "importance": self.importance,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    def content_for_recall(self) -> str:
        """用于召回的文本表示。"""
        parts = [self.task_summary]
        if self.key_steps:
            parts.append("关键步骤: " + " → ".join(self.key_steps))
        if self.lessons:
            parts.append("经验: " + "; ".join(self.lessons))
        return " | ".join(parts)


class EpisodicStore(abc.ABC):
    """Episodic Memory 持久化契约。"""

    @abc.abstractmethod
    async def save(self, episode: Episode) -> None:
        """保存 Episode。"""

    @abc.abstractmethod
    async def recall(self, query: str, top_k: int = 10) -> list[Episode]:
        """按查询召回相关 Episode。"""

    @abc.abstractmethod
    async def get(self, episode_id: str) -> Episode | None:
        """按 ID 读取。"""

    @abc.abstractmethod
    async def list_by_execution(self, execution_id: str) -> list[Episode]:
        """列出某 execution 的所有 Episode。"""

    @abc.abstractmethod
    async def list_all(self, limit: int = 10000) -> list[Episode]:
        """列出所有 Episode（供 ProceduralExtractor 挖掘模式）。"""

    @abc.abstractmethod
    async def delete(self, episode_id: str) -> bool:
        """删除 Episode（供 MemoryDecayManager 清理）。"""


class InMemoryEpisodicStore(EpisodicStore):
    """进程内 Episodic 存储（测试 / 单进程默认）。

    召回用简单文本匹配（生产环境可替换为向量后端）。
    """

    def __init__(self) -> None:
        self._store: dict[str, Episode] = {}

    async def save(self, episode: Episode) -> None:
        self._store[episode.episode_id] = copy.deepcopy(episode)

    async def recall(self, query: str, top_k: int = 10) -> list[Episode]:
        now = time.time()
        scored: list[tuple[float, Episode]] = []
        for ep in self._store.values():
            sim = text_similarity(query, ep.content_for_recall())
            if sim > 0:
                base = three_factor_score(sim, ep.importance, ep.created_at, now=now)
                outcome_w = _OUTCOME_WEIGHT.get(ep.outcome, 0.5)
                scored.append((base * outcome_w, ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:top_k]]

    async def get(self, episode_id: str) -> Episode | None:
        return self._store.get(episode_id)

    async def list_by_execution(self, execution_id: str) -> list[Episode]:
        return [
            ep for ep in self._store.values() if ep.execution_id == execution_id
        ]

    async def list_all(self, limit: int = 10000) -> list[Episode]:
        return list(self._store.values())[:limit]

    async def delete(self, episode_id: str) -> bool:
        return self._store.pop(episode_id, None) is not None


class EpisodicExtractor:
    """从 TrajectoryRecord 提取有价值的 Episode。

    沉淀策略（should_extract）：
    - 有步骤且执行完成 → 值得沉淀
    - 步骤少于 2 → 太简单，不值得
    - 全部成功 → outcome=SUCCESS，importance=0.7
    - 有错误但最终成功 → outcome=PARTIAL，importance=0.9（有教训）
    - 失败 → outcome=FAILURE，importance=0.6（避免重复犯错）
    """

    def __init__(self, min_steps: int = 2) -> None:
        self._min_steps = min_steps

    def should_extract(self, trajectory: TrajectoryRecord) -> bool:
        """判断这次执行是否值得沉淀为 Episode。"""
        if len(trajectory.steps) < self._min_steps:
            return False
        return True

    def detect_hallucination(self, trajectory: TrajectoryRecord) -> bool:
        """检测连续相同动作产生相同结果 → 幻觉（Reflexion 论文方法）。"""
        if len(trajectory.steps) < 3:
            return False
        for i in range(2, len(trajectory.steps)):
            s0, s1, s2 = trajectory.steps[i - 2], trajectory.steps[i - 1], trajectory.steps[i]
            if s0.name == s1.name == s2.name and s0.result == s1.result == s2.result:
                return True
        return False

    def extract(self, trajectory: TrajectoryRecord) -> Episode:
        """从 TrajectoryRecord 提取 Episode。"""
        steps = trajectory.steps
        has_error = any(s.error for s in steps)
        last_step = steps[-1] if steps else None
        last_has_error = last_step is not None and last_step.error is not None
        is_hallucination = self.detect_hallucination(trajectory)

        if is_hallucination:
            outcome = EpisodeOutcome.FAILURE
            importance = 0.3
        elif last_has_error:
            outcome = EpisodeOutcome.FAILURE
            importance = 0.6
        elif has_error:
            outcome = EpisodeOutcome.PARTIAL
            importance = 0.9
        else:
            outcome = EpisodeOutcome.SUCCESS
            importance = 0.7

        key_steps = [
            f"{s.name}({'✓' if not s.error else '✗'})"
            for s in steps
        ]

        lessons: list[str] = []
        if is_hallucination:
            lessons.append("检测到幻觉：连续相同动作产生相同结果")
        error_steps = [s for s in steps if s.error]
        for s in error_steps:
            lessons.append(f"{s.name} 失败: {s.error}")

        skill_names = list({s.name for s in steps})

        task_summary = trajectory.plan.get("task", "") or trajectory.planner or "execution"
        if isinstance(task_summary, dict):
            task_summary = str(task_summary)

        duration = sum(s.latency for s in steps)

        return Episode(
            execution_id=trajectory.execution_id,
            task_summary=str(task_summary),
            outcome=outcome,
            key_steps=key_steps,
            lessons=lessons,
            skill_names=skill_names,
            total_tokens=trajectory.total_tokens,
            total_cost=trajectory.total_cost,
            duration=duration,
            importance=importance,
            metadata={
                "planner": trajectory.planner,
                "step_count": len(steps),
                "has_forensic": trajectory.forensic is not None,
            },
        )


class EpisodicMemory:
    """Episodic Memory 门面：沉淀 + 召回。

    用法：
    ```
    ep = EpisodicMemory(store)
    # 执行后沉淀
    episode = await ep.remember(trajectory)
    # 下次类似任务召回
    episodes = await ep.recall("会展招商分析")
    ```
    """

    def __init__(
        self,
        store: EpisodicStore,
        extractor: EpisodicExtractor | None = None,
    ) -> None:
        self._store = store
        self._extractor = extractor or EpisodicExtractor()

    async def remember(
        self, trajectory: TrajectoryRecord
    ) -> Episode | None:
        """从 Trajectory 沉淀 Episode。不值得沉淀时返回 None。"""
        if not self._extractor.should_extract(trajectory):
            return None

        episode = self._extractor.extract(trajectory)
        await self._store.save(episode)
        logger.info(
            "episodic memory saved execution=%s outcome=%s importance=%.1f",
            episode.execution_id, episode.outcome.value, episode.importance,
        )
        return episode

    async def recall(self, query: str, top_k: int = 10) -> list[Episode]:
        """召回相关历史经历。"""
        return await self._store.recall(query, top_k)

    async def get(self, episode_id: str) -> Episode | None:
        return await self._store.get(episode_id)

    async def list_by_execution(self, execution_id: str) -> list[Episode]:
        return await self._store.list_by_execution(execution_id)


__all__ = [
    "EpisodeOutcome",
    "Episode",
    "EpisodicStore",
    "InMemoryEpisodicStore",
    "EpisodicExtractor",
    "EpisodicMemory",
]
