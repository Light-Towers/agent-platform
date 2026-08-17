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
    "get_default_backend",
    "get_semantic_memory",
    "recall_memories",
    "remember_memory",
    "DEFAULT_COLLECTION",
    "MilvusMemoryBackend",
    "PgVectorMemoryBackend",
    "create_memory_backend",
]
