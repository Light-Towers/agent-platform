# -*- coding: utf-8 -*-
"""语义长期记忆后端契约（优化 E / P4.3 / E-3）。

仅定义 ``MemoryBackend`` Protocol 签名，**不含任何实现**（尤其不耦合 pgvector /
数据库连接池），以保持 agent-core 零依赖铁律。

实现留在宿主侧（如 ``app.memory.memory_backend.PgVectorMemoryBackend``），通过
``from agent_core.memory.backend import MemoryBackend`` 复用该契约。

注意：本契约与同包 ``base.ConversationMemory``（会话历史存储）是**两套正交能力**——
``ConversationMemory`` 面向「对话轮次持久化」（save/get_recent/clear/update），
``MemoryBackend`` 面向「语义长期记忆召回」（recall/remember）。请勿将二者合并。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBackend(Protocol):
    """语义长期记忆后端契约。

    ``pool`` 为宿主数据库连接池对象（类型由实现方决定，契约层仅用 object 占位，
    避免内核反向依赖具体 DB 驱动）。
    """

    async def recall(self, pool: object, user_id: str, question: str, k: int = 3) -> list[str]:
        """召回与 question 相关的历史记忆文本。"""
        ...

    def remember(self, pool: object, user_id: str, content: str) -> None:
        """沉淀一条记忆（非阻塞）。"""
        ...
