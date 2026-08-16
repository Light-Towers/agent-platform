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

# 优化 E / P4.3 / E-3：MemoryBackend 契约下沉到内核 agent_core.memory.backend，
# 此处 re-export 单一真相源。import 失败时回退到本地副本（S-3 回滚开关）。
try:
    from agent_core.memory.backend import MemoryBackend
except Exception:  # pragma: no cover - 兜底：内核不可用时保留本地定义
    # 刻意保留的 S-3 回滚副本：仅在 agent_core 不可导入时启用，保证 app 侧
    # MemoryBackend 契约不依赖内核可达性。与 agent_core.memory.backend.MemoryBackend
    # 签名必须保持同步（属回退兜底，非业务重复代码，勿删）。
    _MemoryBackend_Local = True

    @runtime_checkable
    class MemoryBackend(Protocol):  # type: ignore[no-redef]
        """长期记忆后端契约（本地回退副本，S-3 红线兜底）。"""

        async def recall(self, pool: object, user_id: str, question: str, k: int = 3) -> list[str]:
            ...

        def remember(self, pool: object, user_id: str, content: str) -> None:
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
    """复合后端：按 namespace 路由到不同后端（预留，当前未启用）。

    ⚠️ 状态：首期**仅接入 pgvector 后端（default），复合路由接口保留但暂不启用**——
    当前行为完全等价于 ``PgVectorMemoryBackend``，属于 Speculative Generality 预留扩展点，
    请勿将其视为已生效的多后端能力。调用方无感知。未来按 namespace 将文件型/缓存型
    记忆路由到独立后端时再启用，无需改动调用方签名。
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
