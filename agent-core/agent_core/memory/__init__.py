# -*- coding: utf-8 -*-
"""
会话记忆子包（框架无关内核）。

- ``base``：``ConversationMemory`` 协议（零 pymongo，可独立单测）；
- ``mongo``：``MongoHistoryStore`` 实现（需要 pymongo，``memory-mongo`` extra）；
- ``backend``：``MemoryBackend`` 语义长期记忆后端契约（零依赖，**仅签名**）。

重要区别（优化 E / E-3 / M-5）：
  ``ConversationMemory`` 面向「对话轮次持久化」（save/get_recent/clear/update），
  ``MemoryBackend`` 面向「语义长期记忆召回」（recall/remember）。二者是正交能力，
  请勿合并。``MemoryBackend`` 的实现（如 pgvector 后端）留在宿主侧，内核只定契约。
"""

from agent_core.memory.base import ConversationMemory
from agent_core.memory.backend import MemoryBackend

__all__ = ["ConversationMemory", "MemoryBackend"]
