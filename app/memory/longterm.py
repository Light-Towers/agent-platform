"""长期记忆：pgvector 语义召回 + 后台异步沉淀（兼容门面）。

逻辑已下沉到 ``memory_backend.PgVectorMemoryBackend``。本模块保留模块级
``recall`` / ``remember`` 函数作为稳定门面，内部委托默认后端单例，调用方
（graph.py）无需改动。如需切换/组合后端，替换 ``memory_backend.default_backend``。
"""

import logging

from app.memory.memory_backend import default_backend

logger = logging.getLogger(__name__)


async def recall(pool, user_id: str, question: str, k: int = 3) -> list[str]:
    return await default_backend.recall(pool, user_id, question, k=k)


def remember(pool, user_id: str, content: str) -> None:
    default_backend.remember(pool, user_id, content)
