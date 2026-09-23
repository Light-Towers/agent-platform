"""Memory 分类枚举 + 召回编排（四类 Memory 阶段 1C）。

按"记住的东西是什么"分类，不同类型用不同存储 / 不同写入机制 / 不同召回策略。

四类 Memory：
- ``WORKING``：当前任务正在发生什么（State / Checkpoint）
- ``EPISODIC``：过去发生过什么（Execution History / Episode）
- ``SEMANTIC``：已知的事实/知识是什么（RDB / KG / Vector DB / RAG）
- ``PROCEDURAL``：已经掌握的做事方法是什么（Skill / Workflow / Policy）

``MemoryRetriever`` 协议统一召回接口，``ContextSelector`` 按任务类型选哪些 Memory 参与。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MemoryCategory(str, Enum):
    """四类 Memory 分类（按信息语义/用途，非按保存时间）。"""

    WORKING = "working"  # 当前任务状态
    EPISODIC = "episodic"  # 过去执行经历
    SEMANTIC = "semantic"  # 业务事实/知识
    PROCEDURAL = "procedural"  # 做事方法/Skill


@dataclass
class MemoryRecallRequest:
    """统一召回请求。"""

    query: str
    execution_id: str | None = None  # Working Memory 需要
    tenant_id: str | None = None
    user_id: str | None = None
    workspace_id: str | None = None
    task_type: str | None = None  # 任务类型（供 ContextSelector 决策）
    top_k: int = 10
    categories: set[MemoryCategory] = field(default_factory=lambda: {
        MemoryCategory.SEMANTIC,
        MemoryCategory.EPISODIC,
    })
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryRecallResult:
    """统一召回结果。"""

    content: str
    category: MemoryCategory
    source: str = ""  # 子来源（shared/user/trajectory/skill/...）
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "category": self.category.value,
            "source": self.source,
            "score": self.score,
            "metadata": self.metadata,
        }


class MemoryRetriever:
    """统一召回协议：按 MemoryCategory 分派到对应 Store。

    各 Memory 类型的 retriever 独立注入，未注入的类型跳过。
    """

    def __init__(
        self,
        working: Any = None,  # WorkingMemory
        episodic: Any = None,  # EpisodicMemory（阶段 2）
        semantic: Any = None,  # SemanticMemory
        procedural: Any = None,  # ProceduralMemory（阶段 3）
    ) -> None:
        self._retrievers: dict[MemoryCategory, Any] = {}
        if working is not None:
            self._retrievers[MemoryCategory.WORKING] = working
        if episodic is not None:
            self._retrievers[MemoryCategory.EPISODIC] = episodic
        if semantic is not None:
            self._retrievers[MemoryCategory.SEMANTIC] = semantic
        if procedural is not None:
            self._retrievers[MemoryCategory.PROCEDURAL] = procedural

    async def recall(
        self, request: MemoryRecallRequest
    ) -> list[MemoryRecallResult]:
        """统一召回：按 request.categories 分派到各 Memory retriever。"""
        all_results: list[MemoryRecallResult] = []

        for category in request.categories:
            retriever = self._retrievers.get(category)
            if retriever is None:
                continue
            try:
                results = await self._recall_one(category, retriever, request)
                all_results.extend(results)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "memory recall failed category=%s", category.value, exc_info=True
                )

        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[: request.top_k]

    async def _recall_one(
        self,
        category: MemoryCategory,
        retriever: Any,
        request: MemoryRecallRequest,
    ) -> list[MemoryRecallResult]:
        """单类 Memory 召回。"""
        if category is MemoryCategory.WORKING:
            if request.execution_id is None:
                return []
            snap = await retriever.snapshot(request.execution_id)
            return [
                MemoryRecallResult(
                    content=str(snap.to_dict()),
                    category=MemoryCategory.WORKING,
                    source="checkpoint",
                    score=1.0,
                    metadata=snap.to_dict(),
                )
            ]

        if category is MemoryCategory.SEMANTIC:
            from agent_runtime.semantic_memory import SemanticRecallRequest

            sem_req = SemanticRecallRequest(
                query=request.query,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                top_k=request.top_k,
                filters=request.filters,
            )
            sem_results = await retriever.recall(sem_req)
            return [
                MemoryRecallResult(
                    content=r.content,
                    category=MemoryCategory.SEMANTIC,
                    source=r.source,
                    score=r.score,
                    metadata=r.metadata,
                )
                for r in sem_results
            ]

        if category is MemoryCategory.EPISODIC:
            if hasattr(retriever, "recall"):
                return await retriever.recall(request)
            return []

        if category is MemoryCategory.PROCEDURAL:
            if hasattr(retriever, "recall"):
                return await retriever.recall(request)
            return []

        return []


@dataclass
class ContextSelection:
    """ContextSelector 决策结果：哪些 Memory 参与召回。"""

    categories: set[MemoryCategory]
    reason: str = ""


class ContextSelector:
    """按任务类型选哪些 Memory 参与召回（避免 Context Pollution）。

    不同任务类型需要不同的 Memory 组合：
    - 问答：Semantic（知识）+ Episodic（相似经历）
    - 执行：Working（当前状态）+ Procedural（相关 Skill）
    - 分析：Semantic + Episodic + Procedural
    - 审批：Working（当前状态）
    """

    DEFAULT_SELECTION: dict[str, set[MemoryCategory]] = {
        "qa": {MemoryCategory.SEMANTIC, MemoryCategory.EPISODIC},
        "execute": {MemoryCategory.WORKING, MemoryCategory.PROCEDURAL},
        "analyze": {
            MemoryCategory.SEMANTIC,
            MemoryCategory.EPISODIC,
            MemoryCategory.PROCEDURAL,
        },
        "approve": {MemoryCategory.WORKING},
        "chat": {MemoryCategory.SEMANTIC, MemoryCategory.EPISODIC},
    }

    def select(
        self,
        task_type: str | None = None,
        execution_id: str | None = None,
    ) -> ContextSelection:
        """选择参与召回的 Memory 类型。"""
        if task_type is None:
            return ContextSelection(
                categories={MemoryCategory.SEMANTIC, MemoryCategory.EPISODIC},
                reason="default: semantic + episodic",
            )

        categories = self.DEFAULT_SELECTION.get(task_type)
        if categories is None:
            return ContextSelection(
                categories={MemoryCategory.SEMANTIC, MemoryCategory.EPISODIC},
                reason=f"unknown task_type={task_type}, default",
            )

        reason = f"task_type={task_type}"
        if execution_id is not None and MemoryCategory.WORKING in categories:
            reason += f", execution={execution_id}"

        return ContextSelection(categories=categories, reason=reason)


__all__ = [
    "MemoryCategory",
    "MemoryRecallRequest",
    "MemoryRecallResult",
    "MemoryRetriever",
    "ContextSelection",
    "ContextSelector",
]
