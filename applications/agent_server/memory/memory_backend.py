# -*- coding: utf-8 -*-
"""类型化记忆薄适配层（ADR-0004 阶段 1，re-export 内核）。

本文件原本承载「类型化读写 / 加权融合 / 遗忘」全部逻辑（优化 H），现下沉为
``agent_core.memory.typed`` 内核可选模块，app 与 deepagents 共用单一真相源
（见 ADR-0004 v2.1 驱动策略 6）。

本层只做三件事：
1. 复用 app 既有 psycopg 池（不自建池，遵守 ADR-0003 单一连接源）；
2. 用 app 自有 embedder 计算向量（内核不下沉 embedder，embedding 由宿主层提供）；
3. 把内核 ``recall_typed`` 的 ``list[TypedMemory]`` 投影回 app 既有契约
   ``recall_typed -> list[str]``，保持 ``longterm.py`` 与既有测试不变。

开关：
- 关闭 ``SEMANTIC_MEMORY_TYPED`` 时，内核 ``recall_typed`` 退化为平权召回，
  app 沿用自身 psycopg 池，连接来源不变（ADR-0004 约束 7）。
"""

from __future__ import annotations

from typing import Iterable

# 内核类型化记忆（单一真相源）
from agent_core.memory.typed import (
    MemoryType,
    TypedMemory,
    semantic_memory_typed_enabled,
)
from agent_core.memory.typed import (
    consolidate as _core_consolidate,
)
from agent_core.memory.typed import (
    forget as _core_forget,
)
from agent_core.memory.typed import (
    recall_typed as _core_recall_typed,
)
from agent_core.memory.typed import (
    remember_typed as _core_remember_typed,
)

# 降级路径（无 DB/内核后端）的门面：app 仍用自己的 _resolve_default_backend
# （基于 database_url 解析，与内核 get_default_backend 的 SEMANTIC_MEMORY_ENABLED
# 开关解耦），保持既有 app 测试契约不变。类型化读写已下沉内核 typed 模块。
from agent_server.config import get_settings

default_backend = None


def _resolve_default_backend():
    """解析默认内核后端：有 DATABASE_URL 时返回 PgVectorMemoryBackend，否则 None。"""
    global default_backend
    if default_backend is not None:
        return default_backend
    # 动态经 app.config 模块取值：允许测试 monkeypatch app.config.get_settings
    import agent_server.config as _cfg

    url = _cfg.get_settings().database_url
    if not url:
        default_backend = None
        return None
    from agent_core.memory.vector_backend import PgVectorMemoryBackend

    default_backend = PgVectorMemoryBackend(
        database_url=url, tenant_id=None, embedder=_AppEmbedder()
    )
    return default_backend


class _AppEmbedder:
    """把 app 的 embed_texts(module 函数) 适配为内核 Embedder 协议（dim + embed）。"""

    def __init__(self) -> None:
        import agent_server.config as _cfg

        self.dim = _cfg.get_settings().vector_dim

    async def embed(self, texts):
        from agent_server.rag.embed import embed_texts

        return embed_texts(texts, dim=self.dim)


def get_default_backend():
    """app 门面：复用内核 PgVectorMemoryBackend（降级路径）。"""
    return _resolve_default_backend()

_MEMORY_TYPES = {"episodic", "semantic", "procedural"}


def embed_memory(text: str) -> list[float]:
    """用 app 自有 embedder 计算记忆向量（512 维，与 memories 表一致）。

    直接复用 ``app.rag.embed.embed_texts``，避免依赖内核默认 embedder 选型，
    保持与 RAG/缓存维度统一（CI 零密钥）。内核 typed 模块不内嵌 embedder，
    embedding 必须由宿主层在此处提供。
    """
    from agent_server.rag.embed import embed_texts

    return embed_texts([text], dim=get_settings().vector_dim)[0]


async def remember_fact(
    pool,
    workspace_id: str,
    fact: str,
    memory_type: str = "semantic",
    importance: float = 0.5,
) -> None:
    """沉淀一条带类型/重要性的结构化记忆（ADO-0004 re-export）。

    ``workspace_id`` 复用内核 ``remember_typed(pool, user_id, ...)`` 的 user_id 形参位，
    与优化 G 的隔离维度一致；``memory_type`` 取 episodic/semantic/procedural。
    实现委托内核 ``typed.remember_typed``（列顺序与旧实现完全一致，
    以便既有测试 ``test_remember_fact_writes_typed`` 不变）。
    """
    if memory_type not in _MEMORY_TYPES:
        memory_type = "semantic"
    importance = max(0.0, min(1.0, float(importance)))
    emb = embed_memory(fact)
    await _core_remember_typed(
        pool,
        user_id=workspace_id,
        fact=fact,
        memory_type=memory_type,
        importance=importance,
        embedding=emb,
    )


async def recall_typed(
    pool,
    workspace_id: str,
    question: str,
    k: int = 3,
    weights: Iterable[tuple[str, float]] | None = None,
) -> list[str]:
    """分层加权召回（ADR-0004 re-export，向下投影为 list[str]）。

    委托内核 ``typed.recall_typed``（按 type_weight × importance × time_decay 融合），
    再投影 ``TypedMemory.content`` 回 app 既有 ``list[str]`` 契约，保持
    ``longterm.recall`` 与既有测试不变。``SEMANTIC_MEMORY_TYPED`` 关闭时内核降级平权召回。
    """
    emb = embed_memory(question)
    typed: list[TypedMemory] = await _core_recall_typed(
        pool,
        user_id=workspace_id,
        question=question,
        k=k,
        weights=weights,
        embedding=emb,
    )
    return [m.content for m in typed]


async def consolidate_memories(
    pool,
    workspace_id: str,
    forget_threshold: float | None = None,
    age_days: int | None = None,
) -> int:
    """巩固 + 遗忘（ADR-0004 re-export，委托内核 typed.consolidate，TD-6 参数化）。

    - forgetting：淘汰 importance 低于阈值且超过 age_days 天的低价值记忆；
    - ``forget_threshold`` / ``age_days`` 为 ``None`` 时由内核取环境变量默认值
      （``MEMORY_FORGET_THRESHOLD`` / ``MEMORY_FORGET_AGE_DAYS``，默认 0.1 / 30）；
    - 返回被淘汰的记忆条数。
    """
    return await _core_consolidate(
        user_id=workspace_id,
        pool=pool,
        forget_threshold=forget_threshold,
        age_days=age_days,
    )


async def forget_memory(pool, workspace_id: str, memory_id: int) -> bool:
    """按 id 显式遗忘一条记忆（ADR-0004 re-export，委托内核 typed.forget）。"""
    return await _core_forget(
        user_id=workspace_id,
        pool=pool,
        memory_id=memory_id,
    )


# 兼容别名：内核 MemoryType / TypedMemory 透出，便于上层直接引用
__all__ = [
    "MemoryType",
    "TypedMemory",
    "semantic_memory_typed_enabled",
    "get_default_backend",
    "_resolve_default_backend",
    "default_backend",
    "embed_memory",
    "remember_fact",
    "recall_typed",
    "consolidate_memories",
    "forget_memory",
]
