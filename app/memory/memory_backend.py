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
