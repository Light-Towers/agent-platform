"""Episode 去重/压缩：防止 Episodic Memory 无限膨胀。

按 (task_summary, outcome) 分组，同组保留 importance 最高的为主 Episode，
合并 lessons / skill_names（去重），累加 token/cost/duration，
metadata.dedup_count 记录合并条数。

当前用精确匹配（task_summary 完全相同）。模糊去重（语义相似度）需 embedding，
属于向量检索方向（P4），此处预留 similarity_threshold 参数。
"""

from __future__ import annotations

import logging
from dataclasses import replace

from agent_runtime.episodic_memory import Episode, EpisodeOutcome

logger = logging.getLogger(__name__)


class EpisodeDeduplicator:
    """对 Episodic Memory 做去重/压缩。

    用法：
    ```
    dedup = EpisodeDeduplicator()
    unique, merged_count = dedup.deduplicate(all_episodes)
    ```
    """

    def __init__(self, similarity_threshold: float = 1.0) -> None:
        """similarity_threshold=1.0 表示精确匹配（task_summary 完全相同才合并）。
        <1.0 需 embedding 相似度，当前不支持。
        """
        self._threshold = similarity_threshold

    def deduplicate(
        self, episodes: list[Episode]
    ) -> tuple[list[Episode], int]:
        """去重，返回 (去重后列表, 合并条数)。"""
        if not episodes:
            return [], 0

        groups: dict[tuple[str, EpisodeOutcome], list[Episode]] = {}
        for ep in episodes:
            key = (ep.task_summary, ep.outcome)
            groups.setdefault(key, []).append(ep)

        result: list[Episode] = []
        merged_count = 0

        for key, group in groups.items():
            if len(group) == 1:
                result.append(group[0])
                continue

            group.sort(key=lambda e: e.importance, reverse=True)
            primary = group[0]
            duplicates = group[1:]

            merged_lessons = list(primary.lessons)
            seen_lessons = set(merged_lessons)
            for ep in duplicates:
                for lesson in ep.lessons:
                    if lesson not in seen_lessons:
                        merged_lessons.append(lesson)
                        seen_lessons.add(lesson)

            merged_skills = list(primary.skill_names)
            seen_skills = set(merged_skills)
            for ep in duplicates:
                for skill in ep.skill_names:
                    if skill not in seen_skills:
                        merged_skills.append(skill)
                        seen_skills.add(skill)

            total_tokens = primary.total_tokens + sum(
                ep.total_tokens for ep in duplicates
            )
            total_cost = primary.total_cost + sum(
                ep.total_cost for ep in duplicates
            )
            duration = primary.duration + sum(ep.duration for ep in duplicates)

            dedup_count = len(duplicates) + primary.metadata.get("dedup_count", 0)
            new_metadata = {**primary.metadata, "dedup_count": dedup_count}

            merged = replace(
                primary,
                lessons=merged_lessons,
                skill_names=merged_skills,
                total_tokens=total_tokens,
                total_cost=total_cost,
                duration=duration,
                metadata=new_metadata,
            )
            result.append(merged)
            merged_count += len(duplicates)

        if merged_count > 0:
            logger.info(
                "episode dedup: %d episodes → %d unique (%d merged)",
                len(episodes),
                len(result),
                merged_count,
            )

        return result, merged_count


__all__ = ["EpisodeDeduplicator"]
