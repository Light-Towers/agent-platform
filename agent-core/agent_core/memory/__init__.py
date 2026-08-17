# -*- coding: utf-8 -*-
"""
会话记忆子包（框架无关内核，所有子包共享的单一真相源）。

- ``base``：``ConversationMemory`` 协议（零依赖，对话轮次持久化）；
- ``mongo``：``MongoHistoryStore`` 实现（对话历史，pymongo / ``memory-mongo`` extra）；
- ``backend``：``MemoryBackend`` 语义长期记忆后端契约（零依赖，**仅签名**）；
- ``embedder``：共享 Embedding 提供方（远程硅基流动 / 本地 bge 动态切换）；
- ``vector_backend``：语义记忆向量后端（Milvus 默认 + PgVector 备选，可切换）；
- ``mongo_checkpointer``：LangGraph ``MongoCheckpointer``（会话历史持久化到 Mongo）；
- ``semantic``：语义记忆门面（recall_memories / remember_memory），统一上游调用。

重要区别（优化 E / E-3 / M-5）：
  ``ConversationMemory`` 面向「对话轮次持久化」（save/get_recent/clear/update），
  ``MemoryBackend`` 面向「语义长期记忆召回」（recall/remember）。二者是正交能力，
  请勿合并。所有后端实现现已收口到内核，**各子包不得再各自为政重复实现**——
  统一从此处 import。
"""

from agent_core.memory.base import ConversationMemory
from agent_core.memory.backend import MemoryBackend
from agent_core.memory.embedder import (
    EmbeddingProvider,
    LocalEmbedder,
    SiliconFlowEmbedder,
    RemoteEmbedder,
    get_embedder,
)
from agent_core.memory.mongo import MongoHistoryStore
from agent_core.memory.mongo_checkpointer import MongoCheckpointer
from agent_core.memory.semantic import (
    get_default_backend,
    get_semantic_memory,
    recall_memories,
    remember_memory,
)
from agent_core.memory.vector_backend import (
    DEFAULT_COLLECTION,
    MilvusMemoryBackend,
    PgVectorMemoryBackend,
    create_memory_backend,
)


def get_checkpointer():
    """构建 LangGraph checkpointer（各子包统一入口，类比 ``get_embedder``）。

    优先级：
      1. 配置 ``MONGO_URL`` → ``MongoCheckpointer``（持久化到 MongoDB，重启不丢，
         按 ``tenant_id`` 隔离）。生产推荐。
      2. 否则降级 ``InMemorySaver``（纯内存，重启丢，开发/无 Mongo 环境）。

    所有子包应通过本工厂获取 checkpointer，避免在各处重复 ``if MONGO_URL ...
    else InMemorySaver`` 样板，并保证降级策略一致。
    """
    mongo_url = __import__("os").getenv("MONGO_URL")
    if mongo_url:
        try:
            return MongoCheckpointer(
                mongo_url=mongo_url,
                db_name=__import__("os").getenv("MONGO_DB", "deepagents"),
                collection=__import__("os").getenv(
                    "MONGO_CHECKPOINT_COLLECTION", "langgraph_checkpoints"
                ),
                tenant_id=__import__("os").getenv("TENANT_ID", "default"),
            )
        except Exception as e:  # pragma: no cover - Mongo 不可用时降级
            import logging

            logging.getLogger(__name__).warning(
                "MongoCheckpointer 初始化失败，降级 InMemorySaver: %s", e
            )
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()

__all__ = [
    "ConversationMemory",
    "MemoryBackend",
    "EmbeddingProvider",
    "LocalEmbedder",
    "SiliconFlowEmbedder",
    "RemoteEmbedder",
    "get_embedder",
    "MongoHistoryStore",
    "MongoCheckpointer",
    "get_checkpointer",
    "get_default_backend",
    "get_semantic_memory",
    "recall_memories",
    "remember_memory",
    "DEFAULT_COLLECTION",
    "MilvusMemoryBackend",
    "PgVectorMemoryBackend",
    "create_memory_backend",
]
