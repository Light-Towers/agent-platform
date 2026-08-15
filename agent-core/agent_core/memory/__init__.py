# -*- coding: utf-8 -*-
"""
会话记忆子包（框架无关内核）。

- ``base``：``ConversationMemory`` 协议（零 pymongo，可独立单测）；
- ``mongo``：``MongoHistoryStore`` 实现（需要 pymongo，``memory-mongo`` extra）。
"""

from agent_core.memory.base import ConversationMemory

__all__ = ["ConversationMemory"]
