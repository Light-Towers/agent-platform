# -*- coding: utf-8 -*-
"""
会话记忆协议（框架无关内核，源自 zhiku mongo_history_utils）。

定义宿主无关的 ``ConversationMemory`` 协议：``save`` / ``get_recent`` / ``clear`` / ``update``。
任何持久化后端（Mongo / Redis / 内存）实现该协议即可被 agent 复用。

框架无关：本模块**零 pymongo / 零第三方依赖**，仅 stdlib + typing。
"""

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class ConversationMemory(Protocol):
    """会话记忆存储协议（最小接口）。"""

    def save(self, session_id: str, role: str, text: str, **kwargs: Any) -> str:
        """写入/更新一条会话记录，返回记录主键字符串。

        :param session_id: 会话标识
        :param role: 消息角色（user / assistant）
        :param text: 消息内容
        :param kwargs: 后端相关扩展字段（如 message_id / rewritten_query / item_names 等）
        :return: 记录主键（新增返回新 id，更新返回传入 id）
        """
        ...

    def get_recent(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """返回指定会话最近 ``limit`` 条记录（时间正序），失败返回空列表。"""
        ...

    def clear(self, session_id: str) -> int:
        """清空指定会话的全部历史，返回删除条数。"""
        ...

    def update(self, message_id: str, **kwargs: Any) -> int:
        """按主键更新一条记录，返回更新条数。"""
        ...


__all__ = ["ConversationMemory"]
