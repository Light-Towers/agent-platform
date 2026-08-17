"""长期记忆后端（委托内核 agent_core，消除各自为政）。

原 ``PgVectorMemoryBackend`` / ``CompositeMemoryBackend`` 本地实现已收口到
``agent_core.memory.vector_backend.PgVectorMemoryBackend``（单一真相源）。此处仅
保留进程级默认后端单例 ``default_backend``，并负责按运行时配置（是否启用 DB）选择
内核后端实例或降级为 ``None``（内存模式）。

调用方（graph.py）通过 ``app.memory.longterm.recall/remember`` 门面调用，零改动。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 进程级默认后端单例（None 表示内存模式/未启用语义记忆）。
default_backend: Any = None


def _resolve_default_backend() -> Any:
    """根据运行时配置构建内核 PgVectorMemoryBackend（仅 pg 备选后端，app 用 pg）。

    内存模式（无 DATABASE_URL）降级为 None，保持 app 零 DB 依赖约定。
    """
    global default_backend
    if default_backend is not None:
        return default_backend
    from app.config import get_settings

    settings = get_settings()
    database_url = getattr(settings, "database_url", "") or ""
    if not database_url:
        logger.info("长期记忆后端未启用（内存模式：DATABASE_URL 为空）")
        default_backend = None
        return default_backend
    try:
        from agent_core.memory.embedder import LocalFnEmbedder
        from agent_core.memory.vector_backend import PgVectorMemoryBackend
        from app.rag.embed import embed_texts

        # 注入 app 自有 embedding（512 维, 含 mock/OpenAI 兼容），保持与 memories 表
        # 维度一致 + CI 零密钥约定，而非强制内核共享 embedder。
        app_embedder = LocalFnEmbedder(embed_texts, dim=settings.vector_dim)
        default_backend = PgVectorMemoryBackend(
            database_url=database_url,
            collection="memories",
            tenant_id=None,  # app 的 memories 表无 tenant 列
            embedder=app_embedder,
        )
        logger.info("长期记忆后端已启用（内核 PgVectorMemoryBackend + app embedder, 表=memories）")
    except Exception as e:  # pragma: no cover - 内核后端不可用则降级
        logger.warning("内核 PgVectorMemoryBackend 初始化失败，降级为无记忆: %s", e)
        default_backend = None
    return default_backend


def get_default_backend() -> Any:
    return _resolve_default_backend()


# ---------------------------------------------------------------------------
# 优化 H：类型感知记忆读写（app 层，不触碰 agent-core 内核契约）
#
# 内核 PgVectorMemoryBackend 的 recall/remember 仅支持 (user_id, content, embedding)
# 三元组，无法承载 memory_type/importance。遵循 §3 护栏第 1 条（内核零依赖铁律），
# 此处用 app 自有 psycopg 池 + app embedder 直接操作 memories 表扩展列，与内核
# 后端并存：降级路径（无 DB）仍走内核 recall/remember，类型增强路径走本实现。
# ---------------------------------------------------------------------------

_MEMORY_TYPES = ("episodic", "semantic", "procedural")


def embed_memory(text: str) -> list[float]:
    """用 app 自有 embedder 计算记忆向量（512 维，与 memories 表一致）。

    直接复用 ``app.rag.embed.embed_texts``，避免依赖内核默认 embedder 选型，
    保持与 RAG/缓存维度统一（CI 零密钥）。
    """
    from app.rag.embed import embed_texts
    from app.config import get_settings

    return embed_texts([text], dim=get_settings().vector_dim)[0]


async def remember_fact(
    pool,
    workspace_id: str,
    fact: str,
    memory_type: str = "semantic",
    importance: float = 0.5,
) -> None:
    """沉淀一条带类型/重要性的结构化记忆（优化 H）。

    ``workspace_id`` 复用内核 ``recall(pool, user_id, ...)`` 的 user_id 形参位，
    与优化 G 的隔离维度一致；``memory_type`` 取 episodic/semantic/procedural。
    """
    if memory_type not in _MEMORY_TYPES:
        memory_type = "semantic"
    importance = max(0.0, min(1.0, float(importance)))
    emb = embed_memory(fact)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO memories (user_id, content, embedding, memory_type, importance) "
            "VALUES (%s, %s, %s, %s, %s)",
            (workspace_id, fact, emb, memory_type, importance),
        )


async def recall_typed(
    pool,
    workspace_id: str,
    question: str,
    k: int = 3,
) -> list[str]:
    """分层加权召回（优化 H）。

    语义召回 memories 后，按 memory_type 加权 × importance 衰减排序融合，
    返回 k 条文本。procedural/semantic 略高于 episodic，旧记忆按时间衰减。
    """
    emb = embed_memory(question)
    rows = await vector_search_memories(pool, workspace_id, emb, k=k * 2)
    if not rows:
        return []
    # rows: (content, memory_type, importance, created_at)
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    scored = []
    for content, mtype, imp, created_at in rows:
        type_weight = {"procedural": 1.2, "semantic": 1.1, "episodic": 1.0}.get(
            mtype, 1.0
        )
        age_days = max(0.0, (now - (created_at or now)).total_seconds() / 86400.0)
        decay = 1.0 / (1.0 + 0.01 * age_days)  # 时间衰减（30天约 0.77）
        score = type_weight * float(imp) * decay
        scored.append((score, content))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


async def vector_search_memories(pool, workspace_id: str, embedding: list[float], k: int = 6):
    """memories 表带类型的向量召回，返回 (content, memory_type, importance, created_at)。"""
    from app.infra.db import vector_search

    rows = await vector_search(
        pool,
        table="memories",
        cols="content, memory_type, importance, created_at",
        embedding=embedding,
        k=k,
        where="user_id = %s AND embedding IS NOT NULL",
        where_params=(workspace_id,),
    )
    return [(r[0], r[1], r[2], r[3]) for r in rows]


async def consolidate_memories(
    pool,
    workspace_id: str,
    forget_threshold: float = 0.1,
) -> int:
    """巩固 + 遗忘（优化 H，D4/D5）。

    - forgetting：淘汰 importance 低于阈值且超过 30 天的低价值记忆；
    - 返回被淘汰的记忆条数。
    冲突更新/相似合并由抽取阶段（同一 fact 重复写）在应用层去重，此处做惰性淘汰。
    """
    deleted = 0
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM memories "
            "WHERE user_id = %s AND importance < %s "
            "AND created_at < now() - interval '30 days'",
            (workspace_id, forget_threshold),
        )
        deleted = getattr(cur, "rowcount", 0) or 0
    return deleted


async def forget_memory(pool, workspace_id: str, memory_id: int) -> bool:
    """按 id 显式遗忘一条记忆（优化 H）。"""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM memories WHERE id = %s AND user_id = %s",
            (memory_id, workspace_id),
        )
        return (getattr(cur, "rowcount", 0) or 0) > 0
