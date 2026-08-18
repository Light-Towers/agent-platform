# -*- coding: utf-8 -*-
"""语义长期记忆门面（deepagents 薄封装 + ADR-0004 阶段2 类型化增强）。

历史：本文件原先只是 agent-core 原始语义记忆（``recall_memories``/
``remember_memory`` 的纯 re-export，无类型）。阶段 2 在保持旧门面兼容的
前提下，新增类型化记忆封装（``recall_typed`` / ``remember_typed`` /
``consolidate`` / ``forget``），委托下沉到 agent-core 的 ``typed`` 模块
（PR #9 / ADR-0004），使 deepagents 长期记忆具备类型增强，与 app 共用单一真相源。

驱动策略（ADR-0004 约束 / ADR-0003）：
- typed API 以 ``pool`` 为**必需参数**，接收调用方传入的宿主 psycopg 池
  （``%s`` 风格 + ``pool.connection()``），deepagents 不自建池，避免双池
  违反 ADR-0003；embedder 复用 agent-core 统一单例（``get_embedder``），
  与 cache/intent 层同手法，不下沉 embedder 选型。
- 开关 ``SEMANTIC_MEMORY_TYPED``（默认 false）：
  - true  → 走内核 typed API（类型化加权融合 + 遗忘）。
  - false → 回退内核旧 ``recall_memories``/``remember_memory``（零行为变更），
            ``consolidate``/``forget`` 在 typed 关闭时无操作，保持无回归。
- 不在 main_agent 强制接线：当前 run_deep_agent 无明确记忆落库/召回点，按
  ADR-0004 阶段2 仅暴露 API，避免破坏现有 deepagents 行为。
"""

from __future__ import annotations

from typing import Iterable

from agent_core.logging import get_logger
from agent_core.memory import (
    get_default_backend,
    get_semantic_memory,
    recall_memories,
    remember_memory,
    semantic_memory_enabled,
)
from agent_core.memory.typed import (
    MemoryType,
    TypedMemory,
    consolidate as _core_consolidate,
    forget as _core_forget,
    recall_typed as _core_recall_typed,
    remember_typed as _core_remember_typed,
    semantic_memory_typed_enabled,
)

logger = get_logger(__name__)

_MEMORY_TYPES = {"episodic", "semantic", "procedural"}


def embed_memory(text: str) -> list[float]:
    """用 agent-core 统一 embedder 单例计算记忆向量（不下沉 embedder 选型）。

    与 deepagents 的语义缓存/意图层同手法（``agent_core.memory.embedder.get_embedder``），
    避免重复加载模型、保证向量空间一致。内核 typed API 由宿主层在此提供 embedding。
    """
    from agent_core.memory.embedder import get_embedder

    vec = get_embedder().embed([text])[0]
    return list(vec)


async def remember_fact(
    pool,
    user_id: str,
    fact: str,
    memory_type: str = "semantic",
    importance: float = 0.5,
) -> None:
    """沉淀一条带类型/重要性的结构化记忆（ADR-0004 阶段2 re-export）。

    ``SEMANTIC_MEMORY_TYPED=true`` 时走内核 typed.remember_typed（带类型列）；
    关闭时回退内核旧 ``remember_memory``（保持零行为变更）。``pool`` 为宿主 psycopg 池。
    """
    if memory_type not in _MEMORY_TYPES:
        memory_type = "semantic"
    importance = max(0.0, min(1.0, float(importance)))

    if semantic_memory_typed_enabled():
        emb = embed_memory(fact)
        await _core_remember_typed(
            pool,
            user_id=user_id,
            fact=fact,
            memory_type=memory_type,
            importance=importance,
            embedding=emb,
        )
        return

    # 回退：旧门面（无类型列），零行为变更
    backend = get_default_backend()
    if backend is None:
        logger.warning("SEMANTIC_MEMORY_TYPED=false 且无可用的语义记忆后端，跳过 remember")
        return
    await remember_memory(user_id=user_id, fact=fact, backend=backend)


async def recall_typed(
    pool,
    user_id: str,
    question: str,
    k: int = 3,
    weights: Iterable[tuple[str, float]] | None = None,
) -> list[TypedMemory]:
    """分层加权召回（ADR-0004 阶段2 re-export，返回 list[TypedMemory]）。

    ``SEMANTIC_MEMORY_TYPED=true`` 时走内核 typed.recall_typed（type_weight ×
    importance × time_decay 融合）；关闭时回退内核旧 ``recall_memories``（平权，
    零行为变更），并把结果包装为 ``TypedMemory``（memory_type 默认 semantic、
    importance 0.5）以保持返回类型一致。``pool`` 为宿主 psycopg 池。
    """
    if semantic_memory_typed_enabled():
        emb = embed_memory(question)
        return await _core_recall_typed(
            pool,
            user_id=user_id,
            question=question,
            k=k,
            weights=weights,
            embedding=emb,
        )

    # 回退：旧门面（无类型加权），包装为 TypedMemory 保持契约
    backend = get_default_backend()
    if backend is None:
        logger.warning("SEMANTIC_MEMORY_TYPED=false 且无可用的语义记忆后端，返回空")
        return []
    rows = await recall_memories(user_id=user_id, query=question, backend=backend, limit=k)
    # recall_memories 返回结构不定（取决于后端），尽力提取 content
    result: list[TypedMemory] = []
    for r in rows:
        content = r if isinstance(r, str) else getattr(r, "content", None) or str(r)
        result.append(
            TypedMemory(content=content, memory_type=MemoryType.SEMANTIC, importance=0.5)
        )
    return result


async def consolidate(pool, user_id: str, forget_threshold: float = 0.1) -> int:
    """巩固 + 遗忘（ADR-0004 阶段2 re-export）。

    仅 ``SEMANTIC_MEMORY_TYPED=true`` 时调用内核 typed.consolidate 淘汰低价值记忆；
    关闭时返回 0（deepagents 历史无此能力，保持零行为变更）。``pool`` 为宿主 psycopg 池。
    """
    if not semantic_memory_typed_enabled():
        return 0
    return await _core_consolidate(user_id=user_id, pool=pool, forget_threshold=forget_threshold)


async def forget(pool, user_id: str, memory_id) -> bool:
    """按 id 显式遗忘一条记忆（ADR-0004 阶段2 re-export）。

    仅 ``SEMANTIC_MEMORY_TYPED=true`` 时调用内核 typed.forget；关闭时返回 False
    （deepagents 历史无此能力，保持零行为变更）。``pool`` 为宿主 psycopg 池。
    """
    if not semantic_memory_typed_enabled():
        return False
    return await _core_forget(user_id=user_id, pool=pool, memory_id=memory_id)


__all__ = [
    # 旧门面（保持兼容，零行为变更）
    "semantic_memory_enabled",
    "get_default_backend",
    "get_semantic_memory",
    "recall_memories",
    "remember_memory",
    # 阶段2 类型化增强
    "MemoryType",
    "TypedMemory",
    "semantic_memory_typed_enabled",
    "embed_memory",
    "remember_fact",
    "recall_typed",
    "consolidate",
    "forget",
]
