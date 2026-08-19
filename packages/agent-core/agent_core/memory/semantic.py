# -*- coding: utf-8 -*-
"""语义长期记忆门面（所有子包共享的单一调用入口）。

封装向量后端（Milvus 默认 / PG 备选，来自 vector_backend），向上游提供：
  - ``recall_memories(user_id, question, k)``：跨会话语义召回
  - ``remember_memory(user_id, content)``：非阻塞沉淀记忆

与 ``agent_core.memory.backend.MemoryBackend`` 协议对齐；多租户靠 ``tenant_id`` 隔离
（来自宿主 ContextVar，缺省 "default"）。

向量维度由共享 embedder 动态派生（远程硅基流动 bge-m3=1024 / 本地 bge-small-zh=512）。

环境变量（宿主无关，统一约定）：
  VECTOR_BACKEND=milvus|pg   （默认 milvus）
  MILVUS_URI / MILVUS_TOKEN
  DEEPAGENTS_DATABASE_URL    （pg 后端用；各子包可用各自的 *_DATABASE_URL 覆盖）
  SEMANTIC_MEMORY_COLLECTION （集合/表名，默认 semantic_memory）
  TENANT_ID                  （多租户隔离，默认 default）
  SEMANTIC_MEMORY_ENABLED     （默认 false；开启才真正写入/召回）
  SILICONFLOW_API_KEY         （配了则 embedding 走远程，否则本地）

此前该门面实现在 deepagents/agent/memory/semantic_memory.py，现收口到内核。
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any

from agent_core.logging import get_logger
from agent_core.memory.typed import (
    MemoryType,
    TypedMemory,
    consolidate,
    forget,
    recall_typed,
    remember_typed,
    semantic_memory_typed_enabled,
)
from agent_core.memory.vector_backend import create_memory_backend

logger = get_logger(__name__)


def _database_url() -> str:
    """pg 后端 URL：优先通用 DEEPAGENTS_DATABASE_URL，否则回退通用 DATABASE_URL。

    各子包可注入自己的环境变量名，这里只给通用兜底，避免与宿主耦合。
    """
    return os.getenv("DEEPAGENTS_DATABASE_URL") or os.getenv("DATABASE_URL", "")


@lru_cache(maxsize=1)
def _get_backend() -> Any:
    if os.getenv("SEMANTIC_MEMORY_ENABLED", "false").lower() != "true":
        return None
    mode = os.getenv("VECTOR_BACKEND", "milvus").lower()
    try:
        return create_memory_backend(
            mode=mode,
            uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
            token=os.getenv("MILVUS_TOKEN", ""),
            database_url=_database_url(),
            collection=os.getenv("SEMANTIC_MEMORY_COLLECTION", "semantic_memory"),
            tenant_id=os.getenv("TENANT_ID", "default"),
        )
    except Exception as e:
        logger.warning("语义记忆后端初始化失败，降级为无记忆: %s", e)
        return None


def semantic_memory_enabled() -> bool:
    return _get_backend() is not None


def get_default_backend() -> Any:
    """返回当前语义记忆后端实例（用于显式注入/测试）。"""
    return _get_backend()


async def recall_memories(user_id: str, question: str, k: int = 3) -> list[str]:
    """召回与当前问题相关的历史记忆文本（空列表表示未启用/无结果）。"""
    backend = _get_backend()
    if backend is None or not user_id or not question:
        return []
    try:
        return await backend.recall(pool=None, user_id=user_id, question=question, k=k)
    except Exception as e:
        logger.warning("语义记忆召回失败: %s", e)
        return []


def remember_memory(user_id: str, content: str) -> None:
    """非阻塞沉淀记忆（fire-and-forget，不阻塞主链路）。"""
    backend = _get_backend()
    if backend is None or not user_id or not content:
        return
    try:
        asyncio.get_running_loop().run_in_executor(
            None, lambda: backend.remember(pool=None, user_id=user_id, content=content)
        )
    except RuntimeError:
        # 无运行中的事件循环（如测试/脚本），直接同步调用
        try:
            backend.remember(pool=None, user_id=user_id, content=content)
        except Exception as e:
            logger.warning("语义记忆沉淀失败: %s", e)
    except Exception as e:
        logger.warning("语义记忆沉淀调度失败: %s", e)


# 兼容别名（部分宿主曾直接调用记忆模块工厂）
get_semantic_memory = get_default_backend


__all__ = [
    "semantic_memory_enabled",
    "get_default_backend",
    "get_semantic_memory",
    "recall_memories",
    "remember_memory",
    # ADR-0004 阶段 1：类型化记忆下沉内核（可选模块，不替换上面门面）
    "MemoryType",
    "TypedMemory",
    "semantic_memory_typed_enabled",
    "recall_typed",
    "remember_typed",
    "consolidate",
    "forget",
]
