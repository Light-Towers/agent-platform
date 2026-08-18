# -*- coding: utf-8 -*-
"""类型化记忆下沉内核（ADR-0004 阶段 1）。

本模块把原先只存在于 ``app/memory/memory_backend.py`` 的类型化读写 / 加权融合 /
遗忘逻辑，下沉为 agent-core 的零依赖可选模块，让 app 与 deepagents 共用单一真相源。

设计约束（ADR-0004 v2.1）：
1. 由 ``SEMANTIC_MEMORY_TYPED`` 开关控制，**不替换**现有 ``recall_memories`` /
   ``remember_memory``；旧门面仍可用。
2. ``TypedMemory`` 用 stdlib ``@dataclass``（不引 pydantic，保持内核零依赖）。
3. 内核 API：``recall_typed`` / ``remember_typed`` / ``consolidate`` / ``forget``，
   加权融合 ``type_weight × importance × time_decay``。
4. 与 app 共用宿主 psycopg 池（``%s`` 占位符 + ``pool.connection()``），**不自建
   asyncpg 池**，不依赖 ``app.infra.db.vector_search``，遵守 ADR-0003（单一连接源）。
5. pg 模式 typed 路径接收宿主池直接读 ``memories`` 的类型/重要性/时间列；Milvus
   模式（无类型列）由调用方降级到无类型平权召回，本模块仅提供 SQL 实现。

§3 内核护栏：核心逻辑仅 stdlib；不 import langchain / openai / fastapi / psycopg
（psycopg 仅作为鸭子类型协议在运行时经宿主池传入，不在此硬依赖）。
"""

from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

logger = logging.getLogger(__name__)


# --- 类型定义 --------------------------------------------------------------

class MemoryType(str, Enum):
    """记忆类型枚举（ADR-0004：episodic/semantic/procedural）。"""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"

    @classmethod
    def normalize(cls, value: object) -> "MemoryType":
        """把任意输入归一化为合法 MemoryType；非法值降级 semantic。"""
        if isinstance(value, MemoryType):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.SEMANTIC


@dataclass
class TypedMemory:
    """单条带类型元数据的记忆（零依赖 dataclass）。"""

    content: str
    memory_type: MemoryType
    importance: float
    created_at: datetime.datetime | None = None
    memory_id: object | None = None

    # 融合分，由 recall_typed 填充，便于调试/排序复现
    score: float = 0.0


# --- 默认加权系数（ADR-0004 约束 3）---------------------------------------

DEFAULT_TYPE_WEIGHTS: dict[MemoryType, float] = {
    MemoryType.PROCEDURAL: 1.2,
    MemoryType.SEMANTIC: 1.1,
    MemoryType.EPISODIC: 1.0,
}

TYPE_WEIGHTS_RAW: dict[str, float] = {
    "procedural": 1.2,
    "semantic": 1.1,
    "episodic": 1.0,
}

TIME_DECAY_COEFF: float = 0.01  # 双曲衰减 1/(1 + 0.01*age_days)


# --- 开关 ------------------------------------------------------------------

def semantic_memory_typed_enabled() -> bool:
    """``SEMANTIC_MEMORY_TYPED`` 开关（默认关，保持与旧行为一致）。

    ADR-0004 未拍板「env 覆盖加权系数」，本模块仅用该开关控制 typed 路径是否启用；
    加权系数默认写死，``weights`` 入参可覆盖（约束 2 推荐默认）。
    """
    return os.getenv("SEMANTIC_MEMORY_TYPED", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _normalize_weights(weights: Iterable[tuple[str, float]] | None) -> dict[str, float]:
    """把可选 ``weights`` 入参（(type, weight) 序列）合入默认系数。"""
    merged = dict(TYPE_WEIGHTS_RAW)
    if weights:
        for mtype, w in weights:
            key = MemoryType.normalize(mtype).value
            merged[key] = float(w)
    return merged


def _clamp_importance(importance: float) -> float:
    return max(0.0, min(1.0, float(importance)))


def _time_decay(created_at: datetime.datetime | None, now: datetime.datetime) -> float:
    """双曲时间衰减 1/(1 + 0.01*age_days)；无时间信息时退化为 1.0。"""
    if created_at is None:
        return 1.0
    ref = created_at
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=datetime.timezone.utc)
    age_days = max(0.0, (now - ref).total_seconds() / 86400.0)
    return 1.0 / (1.0 + TIME_DECAY_COEFF * age_days)


def _score_memory(mtype: MemoryType, importance: float, created_at, now,
                  weights: dict[str, float]) -> float:
    type_weight = weights.get(mtype.value, 1.0)
    decay = _time_decay(created_at, now)
    return type_weight * float(importance) * decay


# --- 内核 API（pg 模式，接收宿主 psycopg 池）-------------------------------

async def remember_typed(
    pool,
    user_id: str,
    fact: str,
    memory_type: object = "semantic",
    importance: float = 0.5,
    embedding: list[float] | None = None,
) -> None:
    """沉淀一条带类型/重要性的结构化记忆。

    列顺序与 app 既有 ``memories`` 表一致：
    ``(user_id, content, embedding, memory_type, importance)``，
    以兼容 ``app/memory/memory_backend.py`` 既有 SQL 与既有测试。

    embedding 必须由宿主层提供（内核不下沉 embedder，遵守 ADR-0004 约束：
    ``extract_memory_facts`` 等 LLM 抽取留宿主层）。
    """
    mtype = MemoryType.normalize(memory_type)
    importance = _clamp_importance(importance)
    if embedding is None:
        raise ValueError(
            "embed_memory 由宿主层提供；内核 typed.remember_typed 不内嵌 embedder"
        )
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO memories (user_id, content, embedding, memory_type, importance) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, fact, embedding, mtype.value, importance),
        )


async def recall_typed(
    pool,
    user_id: str,
    question: str,
    k: int = 3,
    weights: Iterable[tuple[str, float]] | None = None,
    embedding: list[float] | None = None,
) -> list[TypedMemory]:
    """分层加权召回（pg 模式）。

    语义召回 memories 后，按 ``type_weight × importance × time_decay`` 融合排序，
    返回 k 条 ``TypedMemory``（score 已填充）。

    embedding 必须由宿主层提供（内核不下沉 embedder）；``question`` 仅作日志上下文，
    不参与打分。若 ``SEMANTIC_MEMORY_TYPED`` 关闭，则退化为平权召回
    （按 created_at 倒序，不加权），保持与旧行为一致。
    """
    if embedding is None:
        raise ValueError(
            "embed_memory 由宿主层提供；内核 typed.recall_typed 不内嵌 embedder"
        )
    rows = await _vector_search_memories(pool, user_id, embedding, k=k * 2)
    if not rows:
        return []
    # rows: (content, memory_type, importance, created_at) 或 (content, created_at) 降级
    now = datetime.datetime.now(datetime.timezone.utc)
    merged = _normalize_weights(weights)
    typed_enabled = semantic_memory_typed_enabled()
    scored: list[TypedMemory] = []
    for row in rows:
        content = row[0]
        if len(row) >= 4:
            mtype = MemoryType.normalize(row[1])
            importance = float(row[2])
            created_at = row[3]
        else:
            # 降级（无类型列，如 Milvus 模式）：平权
            mtype = MemoryType.SEMANTIC
            importance = 0.5
            created_at = row[1] if len(row) > 1 else None
        if typed_enabled:
            score = _score_memory(mtype, importance, created_at, now, merged)
        else:
            # 开关关闭：平权，按时间倒序（created_at 越新分越高）
            decay = _time_decay(created_at, now)
            score = decay
        scored.append(
            TypedMemory(
                content=content,
                memory_type=mtype,
                importance=importance,
                created_at=created_at,
                score=score,
            )
        )
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:k]


async def consolidate(user_id, pool, forget_threshold: float = 0.1) -> int:
    """巩固 + 遗忘（ADR-0004 D4/D5）。

    淘汰「importance 低于阈值且超过 30 天」的低价值记忆，返回删除条数。
    完整 SQL 逻辑，与 app 既有 ``consolidate_memories`` 一致，仅内核化。
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM memories "
            "WHERE user_id = %s AND importance < %s "
            "AND created_at < now() - interval '30 days'",
            (user_id, forget_threshold),
        )
        return getattr(cur, "rowcount", 0) or 0


async def forget(user_id, pool, memory_id) -> bool:
    """按 memory_id 删除单条记忆，返回是否实际删除。"""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM memories WHERE user_id = %s AND id = %s",
            (user_id, memory_id),
        )
        return (getattr(cur, "rowcount", 0) or 0) > 0


# --- 内部：带类型的向量召回（%s 风格，宿主 psycopg 池）---------------------

async def _vector_search_memories(pool, user_id: str, embedding: list[float], k: int = 6):
    """memories 表带类型的向量召回，返回 (content, memory_type, importance, created_at)。

    使用 pgvector 余弦距离 ``embedding <=> %s``；标识符 ``memories`` 写死（内核内部
    单一表名），无注入风险。宿主池须已 ``register_vector`` 并支持 ``<=>>`` 算子。
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT content, memory_type, importance, created_at "
            "FROM memories "
            "WHERE user_id = %s AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s LIMIT %s",
            (user_id, embedding, k),
        )
        return await cur.fetchall()


__all__ = [
    "MemoryType",
    "TypedMemory",
    "DEFAULT_TYPE_WEIGHTS",
    "semantic_memory_typed_enabled",
    "remember_typed",
    "recall_typed",
    "consolidate",
    "forget",
]
