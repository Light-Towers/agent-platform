"""Procedural Memory（四类 Memory 阶段 3）：已经掌握的做事方法是什么。

将 SkillRegistry 的进程内注册升级为**持久化存储**——Skill 定义落库，
重启后自动恢复注册。并从 Episodic Memory 中挖掘高频成功模式 → 候选 Skill。

与其他三类 Memory 的区别：
- Working：当前任务状态
- Episodic：过去执行经历
- Semantic：业务事实/知识
- Procedural：**做事方法**——"我已经学会怎么做这个事情"

闭环：
```
Agent 执行 → Episodic Memory（经历）
    ↓ 高频成功模式
ProceduralExtractor → CandidateSkill
    ↓
ProceduralMemory（持久化 Skill 定义）
    ↓
下次任务 → 匹配 Skill → 直接执行
```
"""

from __future__ import annotations

import abc
import copy
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.episodic_memory import Episode, EpisodeOutcome
from agent_runtime.memory_recall import text_similarity
from agent_runtime.skill_lifecycle import SkillLifecycle

logger = logging.getLogger(__name__)


@dataclass
class ProceduralEntry:
    """Procedural Memory 条目：持久化的 Skill 定义。"""

    name: str
    version: str
    kind: str  # FUNCTION/AGENT/REMOTE/WORKFLOW
    description: str
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    effect_contract: dict[str, Any] | None = None
    lifecycle: str = "stable"  # SkillLifecycle.value
    definition: dict[str, Any] = field(default_factory=dict)  # 完整定义（用于重建）
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "effect_contract": self.effect_contract,
            "lifecycle": self.lifecycle,
            "definition": self.definition,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CandidateSkill:
    """从 Episodic Memory 挖掘的候选 Skill（高频成功模式）。"""

    name: str  # 候选 Skill 名（从 task_summary 提取）
    pattern_steps: list[str]  # 高频步骤序列
    success_count: int = 0
    total_count: int = 0
    avg_tokens: float = 0.0
    avg_cost: float = 0.0
    confidence: float = 0.0  # 置信度（success_rate × frequency）

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_count if self.total_count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pattern_steps": self.pattern_steps,
            "success_count": self.success_count,
            "total_count": self.total_count,
            "success_rate": self.success_rate,
            "avg_tokens": self.avg_tokens,
            "avg_cost": self.avg_cost,
            "confidence": self.confidence,
        }


class ProceduralStore(abc.ABC):
    """Procedural Memory 持久化契约。"""

    @abc.abstractmethod
    async def save(self, entry: ProceduralEntry) -> None:
        """保存 Skill 定义（同 name + version 覆盖）。"""

    @abc.abstractmethod
    async def load(
        self, name: str, version: str | None = None
    ) -> ProceduralEntry | None:
        """加载 Skill 定义。version=None 时返回最新 stable 版本。"""

    @abc.abstractmethod
    async def list_all(self) -> list[ProceduralEntry]:
        """列出所有 Skill 定义。"""

    @abc.abstractmethod
    async def list_by_name(self, name: str) -> list[ProceduralEntry]:
        """列出某 Skill 的所有版本。"""

    @abc.abstractmethod
    async def delete(self, name: str, version: str) -> bool:
        """删除 Skill 定义。"""


class InMemoryProceduralStore(ProceduralStore):
    """进程内 Procedural 存储（测试 / 单进程默认）。"""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], ProceduralEntry] = {}

    async def save(self, entry: ProceduralEntry) -> None:
        entry.updated_at = time.time()
        self._store[(entry.name, entry.version)] = copy.deepcopy(entry)

    async def load(
        self, name: str, version: str | None = None
    ) -> ProceduralEntry | None:
        if version is not None:
            return self._store.get((name, version))
        versions = [e for (n, _v), e in self._store.items() if n == name]
        if not versions:
            return None
        stable = [e for e in versions if e.lifecycle == SkillLifecycle.STABLE.value]
        pool = stable if stable else versions
        return max(pool, key=lambda e: e.version)

    async def list_all(self) -> list[ProceduralEntry]:
        return list(self._store.values())

    async def list_by_name(self, name: str) -> list[ProceduralEntry]:
        return [e for (n, _v), e in self._store.items() if n == name]

    async def delete(self, name: str, version: str) -> bool:
        key = (name, version)
        return self._store.pop(key, None) is not None


class ProceduralMemory:
    """Procedural Memory 门面：Skill 持久化 + 召回。

    用法：
    ```
    proc = ProceduralMemory(store)
    # 持久化 Skill
    await proc.save_skill_definition("search", "1.0.0", "function", "搜索能力", ...)
    # 重启后恢复
    entries = await proc.list_all()
    # 召回相关 Skill
    results = await proc.recall("搜索")
    ```
    """

    def __init__(self, store: ProceduralStore) -> None:
        self._store = store

    async def save_skill_definition(
        self,
        name: str,
        version: str,
        kind: str,
        description: str,
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        effect_contract: dict | None = None,
        lifecycle: str = SkillLifecycle.STABLE.value,
        definition: dict | None = None,
    ) -> ProceduralEntry:
        """持久化 Skill 定义。"""
        entry = ProceduralEntry(
            name=name,
            version=version,
            kind=kind,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            effect_contract=effect_contract,
            lifecycle=lifecycle,
            definition=definition or {},
        )
        await self._store.save(entry)
        logger.info(
            "procedural memory saved skill=%s version=%s", name, version
        )
        return entry

    async def load_skill(
        self, name: str, version: str | None = None
    ) -> ProceduralEntry | None:
        """加载 Skill 定义。"""
        return await self._store.load(name, version)

    async def list_all(self) -> list[ProceduralEntry]:
        """列出所有持久化的 Skill。"""
        return await self._store.list_all()

    async def recall(self, query: str, top_k: int = 10) -> list[ProceduralEntry]:
        """召回相关 Skill（按 bigram Jaccard 相似度）。"""
        all_entries = await self._store.list_all()
        scored: list[tuple[float, ProceduralEntry]] = []
        for e in all_entries:
            sim = max(
                text_similarity(query, e.name),
                text_similarity(query, e.description),
            )
            if sim > 0:
                scored.append((sim, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    async def delete_skill(self, name: str, version: str) -> bool:
        """删除 Skill 定义。"""
        return await self._store.delete(name, version)


class ProceduralExtractor:
    """从 Episodic Memory 挖掘高频成功模式 → 候选 Skill。

    策略：
    - 按 task_summary 分组
    - 同一 task 的成功执行 ≥ min_success 次 → 候选 Skill
    - 提取高频步骤序列作为 pattern_steps
    - confidence = success_rate × log(total_count)
    """

    def __init__(self, min_success: int = 3, min_confidence: float = 0.5) -> None:
        self._min_success = min_success
        self._min_confidence = min_confidence

    def extract_patterns(self, episodes: list[Episode]) -> list[CandidateSkill]:
        """从 Episode 列表挖掘候选 Skill。"""
        import math

        by_task: dict[str, list[Episode]] = {}
        for ep in episodes:
            key = ep.task_summary
            by_task.setdefault(key, []).append(ep)

        candidates: list[CandidateSkill] = []
        for task, task_episodes in by_task.items():
            success_eps = [
                e for e in task_episodes
                if e.outcome in (EpisodeOutcome.SUCCESS, EpisodeOutcome.PARTIAL)
            ]
            if len(success_eps) < self._min_success:
                continue

            step_counter: Counter[tuple[str, ...]] = Counter()
            for ep in success_eps:
                steps_tuple = tuple(ep.skill_names)
                step_counter[steps_tuple] += 1

            if not step_counter:
                continue

            best_pattern, pattern_count = step_counter.most_common(1)[0]
            total = len(task_episodes)
            success_count = len(success_eps)
            success_rate = success_count / total if total > 0 else 0
            confidence = success_rate * math.log(total + 1)

            if confidence < self._min_confidence:
                continue

            avg_tokens = sum(e.total_tokens for e in success_eps) / len(success_eps)
            avg_cost = sum(e.total_cost for e in success_eps) / len(success_eps)

            candidates.append(
                CandidateSkill(
                    name=self._derive_skill_name(task),
                    pattern_steps=list(best_pattern),
                    success_count=success_count,
                    total_count=total,
                    avg_tokens=avg_tokens,
                    avg_cost=avg_cost,
                    confidence=confidence,
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    @staticmethod
    def _derive_skill_name(task_summary: str) -> str:
        """从 task_summary 推导 Skill 名。"""
        import re
        name = re.sub(r"[^\w]", "_", task_summary.lower()).strip("_")
        return f"auto_{name}" if name else "auto_unknown"


__all__ = [
    "ProceduralEntry",
    "CandidateSkill",
    "ProceduralStore",
    "InMemoryProceduralStore",
    "ProceduralMemory",
    "ProceduralExtractor",
]
