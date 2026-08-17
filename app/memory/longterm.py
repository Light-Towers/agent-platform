"""长期记忆：pgvector 语义召回 + 后台异步沉淀（兼容门面）。

实现统一收口到内核 ``agent_core.memory.vector_backend.PgVectorMemoryBackend``
（app 的备选向量后端）。本模块保留模块级 ``recall`` / ``remember`` 作为稳定门面，
内部委托 ``memory_backend.default_backend``。

隔离模型（优化 G）：``workspace_id`` 是长期记忆的隔离主键（跨会话流动、不同空间隔离）。
内核后端 ``recall/remember`` 以 ``user_id`` 形参位承载过滤键，此处将 ``workspace_id``
透传为该过滤键，内核表结构与其余维度保持不变，零侵入。
``user_id`` 仅作辅助归属维度记录，不参与隔离。

注意：内核 PgVectorMemoryBackend 使用独立 asyncpg 连接池（与 app 的 psycopg 池隔离），
故调用时统一传 ``pool=None``，由内核自建/复用池，与 app 现有 psycopg 池解耦。
"""

import logging

from app.memory.memory_backend import get_default_backend

logger = logging.getLogger(__name__)


async def recall(pool, workspace_id: str, question: str, k: int = 3) -> list[str]:
    backend = get_default_backend()
    if backend is None:
        return []
    try:
        # workspace_id 作为内核隔离过滤键（复用 user_id 形参位）
        return await backend.recall(pool=None, user_id=workspace_id, question=question, k=k)
    except Exception:
        logger.exception("长期记忆召回失败，降级为空")
        return []


def remember(pool, workspace_id: str, content: str) -> None:
    backend = get_default_backend()
    if backend is None:
        return
    backend.remember(pool=None, user_id=workspace_id, content=content)
