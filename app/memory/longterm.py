"""长期记忆：pgvector 语义召回 + 后台异步沉淀（兼容门面）。

实现统一收口到内核 ``agent_core.memory.vector_backend.PgVectorMemoryBackend``
（app 的备选向量后端）。本模块保留模块级 ``recall`` / ``remember`` 作为稳定门面，
内部委托 ``memory_backend.default_backend``。

注意：内核 PgVectorMemoryBackend 使用独立 asyncpg 连接池（与 app 的 psycopg 池隔离），
故调用时统一传 ``pool=None``，由内核自建/复用池，与 app 现有 psycopg 池解耦。
调用方（graph.py）签名保持 ``recall(pool, user_id, q, k)`` 以便平滑迁移，pool 参数被忽略。
"""

import logging

from app.memory.memory_backend import get_default_backend

logger = logging.getLogger(__name__)


async def recall(pool, user_id: str, question: str, k: int = 3) -> list[str]:
    backend = get_default_backend()
    if backend is None:
        return []
    try:
        return await backend.recall(pool=None, user_id=user_id, question=question, k=k)
    except Exception:
        logger.exception("长期记忆召回失败，降级为空")
        return []


def remember(pool, user_id: str, content: str) -> None:
    backend = get_default_backend()
    if backend is None:
        return
    backend.remember(pool=None, user_id=user_id, content=content)
