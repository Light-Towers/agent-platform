"""长期记忆后端协议（优化 C）。

定义 ``MemoryBackend`` Protocol，将记忆的存储/召回抽象为可插拔后端。
首期提供 ``PgVectorMemoryBackend``（即原 longterm 的 pgvector 实现）作为默认后端；
``CompositeMemoryBackend`` 预留按 namespace 路由到多后端的接口，但首期复合路由不启用，
仍等价于 pgvector，避免引入未验证的多后端一致性风险。

对外召回/写入签名（recall/remember）保持稳定，调用方（graph.py）零改动。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.infra.cache import spawn_background
from app.infra.db import vector_search
from app.rag.embed import embed_query, embed_texts

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryBackend(Protocol):
    """长期记忆后端契约。"""

    async def recall(self, pool: object, user_id: str, question: str, k: int = 3) -> list[str]:
        """召回与 question 相关的历史记忆文本。"""
        ...

    def remember(self, pool: object, user_id: str, content: str) -> None:
        """沉淀一条记忆（非阻塞）。"""
        ...


class PgVectorMemoryBackend:
    """pgvector 语义召回后端（默认实现）。

    写入走 spawn_background（持引用防 GC）；召回失败静默降级为空，不阻塞主链路。
    """

    async def recall(self, pool, user_id: str, question: str, k: int = 3) -> list[str]:
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

    def remember(self, pool, user_id: str, content: str) -> None:
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


class CompositeMemoryBackend:
    """复合后端：按 namespace 路由到不同后端（预留）。

    首期仅接入 pgvector 后端（default），复合路由接口保留但暂不启用——
    调用方无感知，行为等价于 ``PgVectorMemoryBackend``。未来可按 namespace
    将文件型/缓存型记忆路由到独立后端，无需改动调用方。
    """

    def __init__(self, default: MemoryBackend | None = None) -> None:
        self._default = default or PgVectorMemoryBackend()

    async def recall(self, pool, user_id: str, question: str, k: int = 3, namespace: str = "default") -> list[str]:
        # 首期：所有 namespace 走默认 pgvector 后端；路由扩展点预留。
        return await self._default.recall(pool, user_id, question, k=k)

    def remember(self, pool, user_id: str, content: str, namespace: str = "default") -> None:
        self._default.remember(pool, user_id, content)


# 进程级默认后端单例（保持模块级 recall/remember 门面的内部委托目标）
default_backend: MemoryBackend = PgVectorMemoryBackend()
