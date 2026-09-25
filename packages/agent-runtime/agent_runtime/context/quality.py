"""ContextQualityScorer（Context Governance）：信息质量评分。

不是所有召回的 Memory 质量都一样。本模块对每条 Memory 打质量分，供 Governor
做最终排序和裁剪决策。

三维评分：
- **relevance**：与 query 的语义相关性（bigram Jaccard，复用 memory_recall 的实现）；
- **freshness**：时间衰减（越新越高，半衰期可配）；
- **conflict_degree**：与其他 Memory 的冲突度（内容相似但 metadata 冲突 → 高冲突）。

综合分 = α·relevance + β·freshness + γ·(1 - conflict_degree)，α+β+γ=1。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.memory_recall import text_similarity

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """单条 Memory 的质量评分。"""

    overall: float  # 0-1 综合分
    relevance: float  # 0-1
    freshness: float  # 0-1
    conflict_degree: float  # 0-1，越高越差

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 4),
            "relevance": round(self.relevance, 4),
            "freshness": round(self.freshness, 4),
            "conflict_degree": round(self.conflict_degree, 4),
        }


@dataclass
class QualityReport:
    """质量评分报告。"""

    scores: list[QualityScore] = field(default_factory=list)
    average_quality: float = 0.0
    low_quality_count: int = 0  # overall < threshold 的条数

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": [s.to_dict() for s in self.scores],
            "average_quality": round(self.average_quality, 4),
            "low_quality_count": self.low_quality_count,
        }


class ContextQualityScorer:
    """信息质量评分：relevance + freshness + conflict_degree → overall。

    用法::

        scorer = ContextQualityScorer()
        report = scorer.score(memories, query="如何配置 SSL")
        # report.scores[i].overall 即第 i 条 Memory 的综合质量分
    """

    def __init__(
        self,
        *,
        alpha: float = 0.5,  # relevance 权重
        beta: float = 0.3,  # freshness 权重
        gamma: float = 0.2,  # (1 - conflict_degree) 权重
        freshness_half_life: float = 86400.0 * 7,  # 7 天半衰期
        low_quality_threshold: float = 0.3,
    ) -> None:
        total = alpha + beta + gamma
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"alpha+beta+gamma 必须为 1.0，实际 {total}")
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.freshness_half_life = freshness_half_life
        self.low_quality_threshold = low_quality_threshold

    def score(
        self,
        memories: list[Any],
        query: str,
        *,
        now: float | None = None,
    ) -> QualityReport:
        """对一批 Memory 打质量分。"""
        if not memories:
            return QualityReport()

        current_time = now if now is not None else time.time()
        contents = [_get_content(m) for m in memories]
        metadatas = [_get_metadata(m) for m in memories]

        # 1. relevance
        relevances = [text_similarity(query, c) for c in contents]

        # 2. freshness
        freshnesses = [
            self._freshness(float(meta.get("timestamp", 0.0)), current_time)
            for meta in metadatas
        ]

        # 3. conflict_degree
        conflict_degrees = self._conflict_degrees(contents, metadatas)

        # 4. overall
        scores: list[QualityScore] = []
        for rel, fresh, conf in zip(relevances, freshnesses, conflict_degrees):
            overall = (
                self.alpha * rel
                + self.beta * fresh
                + self.gamma * (1.0 - conf)
            )
            scores.append(
                QualityScore(
                    overall=overall,
                    relevance=rel,
                    freshness=fresh,
                    conflict_degree=conf,
                )
            )

        avg = sum(s.overall for s in scores) / len(scores)
        low_count = sum(1 for s in scores if s.overall < self.low_quality_threshold)
        return QualityReport(scores=scores, average_quality=avg, low_quality_count=low_count)

    def _freshness(self, timestamp: float, now: float) -> float:
        """时间衰减：0.5^((now - timestamp) / half_life)。"""
        if timestamp <= 0:
            return 0.0
        age = now - timestamp
        if age <= 0:
            return 1.0
        return 0.5 ** (age / self.freshness_half_life)

    def _conflict_degrees(
        self,
        contents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> list[float]:
        """冲突度：内容相似但 metadata 中某个关键 key 不同 → 高冲突。"""
        n = len(contents)
        degrees = [0.0] * n
        conflict_keys = ("user_preference", "task_status", "current_step", "active_plan")

        for i in range(n):
            for j in range(i + 1, n):
                sim = text_similarity(contents[i], contents[j])
                if sim < 0.3:
                    continue
                # 内容相似，检查 metadata 是否冲突
                for key in conflict_keys:
                    vi = metadatas[i].get(key)
                    vj = metadatas[j].get(key)
                    if vi is not None and vj is not None and str(vi) != str(vj):
                        conflict_amount = sim * 0.5
                        degrees[i] = max(degrees[i], conflict_amount)
                        degrees[j] = max(degrees[j], conflict_amount)
                        break

        return degrees


def _get_content(mem: Any) -> str:
    """从 MemoryRecallResult 或 dict 提取 content。"""
    if hasattr(mem, "content"):
        return str(mem.content)
    if isinstance(mem, dict):
        return str(mem.get("content", ""))
    return str(mem)


def _get_metadata(mem: Any) -> dict[str, Any]:
    """从 MemoryRecallResult 或 dict 提取 metadata。"""
    if hasattr(mem, "metadata"):
        return dict(mem.metadata or {})
    if isinstance(mem, dict):
        return dict(mem.get("metadata", {}))
    return {}
