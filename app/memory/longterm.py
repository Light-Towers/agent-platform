"""长期记忆：pgvector 语义召回 + 后台异步沉淀。

写入走 spawn_background（持引用防 GC）；召回失败静默降级为空，不阻塞主链路。
"""

import logging

from app.infra.cache import spawn_background
from app.infra.db import vector_search
from app.rag.embed import embed_query, embed_texts

logger = logging.getLogger(__name__)


async def recall(pool, user_id: str, question: str, k: int = 3) -> list[str]:
    if pool is None:
        return []
    try:
        embedding = await embed_query(question)
        rows = await vector_search(
            pool, "memories", "content", embedding, k=k,
            where="user_id = %s AND embedding IS NOT NULL",
            where_params=(user_id,),
        )
        return [r[0] for r in rows]
    except Exception:
        logger.exception("长期记忆召回失败，降级为空")
        return []


def remember(pool, user_id: str, content: str) -> None:
    """非阻塞沉淀；content 为空或池不可用时跳过。"""
    if pool is None or not content.strip():
        return

    async def _write():
        try:
            vec = (await embed_texts([content]))[0]
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO memories (user_id, content, embedding) VALUES (%s, %s, %s)",
                    (user_id, content, vec),
                )
        except Exception:
            logger.exception("长期记忆写入失败")

    spawn_background(_write())
