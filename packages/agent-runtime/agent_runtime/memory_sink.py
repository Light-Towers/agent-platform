"""执行完成后的自动沉淀管道：trajectory → episodic → procedural。

挂载在 execute_plan 的 _persist_trajectory 之后，通过 post_execution_hooks
自动触发，使记忆框架"越用越好"——无需手动调 remember/extract。

闭环：
```
execute_plan 完成
    ↓ post_execution_hooks
EpisodicSink → EpisodicMemory.remember(trajectory) → Episode
    ↓ 每 N 次
ProceduralSink → ProceduralExtractor.extract_patterns() → CandidateSkill
    ↓
ProceduralMemory.save(ProceduralEntry)
    ↓
下次任务 → ProceduralMemory.recall() → 匹配 Skill → 直接执行
    ↓ 执行后
SkillUsageTracker.record_use() → check_and_adjust() → lifecycle 升降级
```
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agent_runtime.episodic_memory import EpisodicMemory
from agent_runtime.procedural_memory import (
    CandidateSkill,
    ProceduralEntry,
    ProceduralExtractor,
    ProceduralStore,
)
from agent_runtime.trajectory.models import TrajectoryRecord

logger = logging.getLogger(__name__)


class EpisodicSink:
    """执行后自动沉淀 Episode。

    作为 post_execution_hook 挂载，每次执行完成后自动调用
    EpisodicMemory.remember(trajectory)，无需手动触发。
    """

    def __init__(self, episodic_memory: EpisodicMemory) -> None:
        self._ep = episodic_memory

    async def __call__(self, trajectory: TrajectoryRecord, runtime: Any) -> None:
        episode = await self._ep.remember(trajectory)
        if episode is not None:
            logger.info(
                "episodic sink: episode=%s outcome=%s importance=%.1f",
                episode.episode_id,
                episode.outcome.value,
                episode.importance,
            )


class ProceduralSink:
    """定期从 Episodic Memory 挖掘候选 Skill → 持久化。

    每 trigger_interval 次执行触发一次 ProceduralExtractor.extract_patterns，
    把高频成功模式沉淀为 ProceduralEntry（lifecycle=draft），供后续验证。
    """

    def __init__(
        self,
        episodic_memory: EpisodicMemory,
        procedural_store: ProceduralStore,
        extractor: ProceduralExtractor | None = None,
        trigger_interval: int = 10,
    ) -> None:
        self._ep = episodic_memory
        self._proc = procedural_store
        self._extractor = extractor or ProceduralExtractor()
        self._interval = trigger_interval
        self._count = 0

    async def __call__(self, trajectory: TrajectoryRecord, runtime: Any) -> None:
        self._count += 1
        if self._count < self._interval:
            return
        self._count = 0

        episodes = await self._ep._store.list_all()
        candidates = self._extractor.extract_patterns(episodes)

        for candidate in candidates:
            await self._save_candidate(candidate, runtime)
            logger.info(
                "procedural sink: candidate=%s confidence=%.2f success=%d/%d",
                candidate.name,
                candidate.confidence,
                candidate.success_count,
                candidate.total_count,
            )

    async def _save_candidate(self, candidate: CandidateSkill, runtime: Any) -> None:
        """把候选 Skill 持久化为 draft ProceduralEntry。

        验证 pattern_steps 是否对应 registry 中已注册的 skill，
        未验证的候选跳过（防止"空壳" skill）。
        """
        if runtime is not None and hasattr(runtime, "registry"):
            valid = all(
                runtime.registry.has(step) for step in candidate.pattern_steps
            )
            if not valid:
                logger.warning(
                    "candidate %s has invalid steps %s, skipping",
                    candidate.name,
                    candidate.pattern_steps,
                )
                return

        existing = await self._proc.load(candidate.name, "auto")
        if existing is not None:
            return

        entry = ProceduralEntry(
            name=candidate.name,
            version="auto",
            kind="function",
            description=f"Auto-extracted pattern (confidence={candidate.confidence:.2f})",
            definition={
                "pattern_steps": candidate.pattern_steps,
                "success_count": candidate.success_count,
                "total_count": candidate.total_count,
                "avg_tokens": candidate.avg_tokens,
                "avg_cost": candidate.avg_cost,
                "confidence": candidate.confidence,
            },
            lifecycle="draft",
        )
        await self._proc.save(entry)


class SkillUsageTracker:
    """记录 Skill 被复用后的效果，自动升降级 lifecycle。

    规则（n ≥ min_uses 时才判定）：
    - draft + success_rate ≥ promote_threshold → stable
    - stable + success_rate < demote_threshold → deprecated
    - 否则保持原级

    用法：
    ```
    tracker = SkillUsageTracker(procedural_memory)
    # skill 被复用后记录效果
    tracker.record_use("search", "1.0", success=True)
    # 定期检查并调整
    await tracker.check_and_adjust("search", "1.0")
    ```
    """

    def __init__(
        self,
        procedural_store: ProceduralStore,
        promote_threshold: float = 0.8,
        demote_threshold: float = 0.3,
        min_uses: int = 5,
    ) -> None:
        self._proc = procedural_store
        self._promote = promote_threshold
        self._demote = demote_threshold
        self._min_uses = min_uses
        self._stats: dict[tuple[str, str], dict[str, int]] = {}

    def record_use(self, name: str, version: str, success: bool) -> None:
        """记录一次 Skill 使用结果。"""
        key = (name, version)
        if key not in self._stats:
            self._stats[key] = {"success": 0, "total": 0}
        self._stats[key]["total"] += 1
        if success:
            self._stats[key]["success"] += 1

    def get_stats(self, name: str, version: str) -> dict[str, int] | None:
        """获取 Skill 使用统计。"""
        return self._stats.get((name, version))

    async def check_and_adjust(self, name: str, version: str) -> str | None:
        """检查 Skill 使用效果，自动调整 lifecycle，返回新 lifecycle 或 None（不变）。"""
        key = (name, version)
        stats = self._stats.get(key)
        if stats is None or stats["total"] < self._min_uses:
            return None

        entry = await self._proc.load(name, version)
        if entry is None:
            return None

        rate = stats["success"] / stats["total"]
        new_lifecycle = entry.lifecycle

        if entry.lifecycle == "draft" and rate >= self._promote:
            new_lifecycle = "stable"
        elif entry.lifecycle == "stable" and rate < self._demote:
            new_lifecycle = "deprecated"

        if new_lifecycle == entry.lifecycle:
            return None

        updated = ProceduralEntry(
            name=entry.name,
            version=entry.version,
            kind=entry.kind,
            description=entry.description,
            input_schema=entry.input_schema,
            output_schema=entry.output_schema,
            effect_contract=entry.effect_contract,
            lifecycle=new_lifecycle,
            definition=entry.definition,
            created_at=entry.created_at,
            updated_at=time.time(),
        )
        await self._proc.save(updated)
        logger.info(
            "skill %s/%s lifecycle %s → %s (rate=%.2f n=%d)",
            name,
            version,
            entry.lifecycle,
            new_lifecycle,
            rate,
            stats["total"],
        )
        return new_lifecycle


__all__ = [
    "EpisodicSink",
    "ProceduralSink",
    "SkillUsageTracker",
]
