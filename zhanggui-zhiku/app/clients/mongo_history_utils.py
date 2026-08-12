# -*- coding: utf-8 -*-
"""
兼容 shim：桥接 agent_core.memory.mongo.MongoHistoryStore，保持旧 import 路径与函数级
API（``save_chat_message`` / ``get_recent_messages`` / ``clear_history`` /
``update_message_item_names``）不变；星号导入 ``from ...mongo_history_utils import *`` 仍可用。

过渡期保留；稳定后调用点应改为直接使用 ``agent_core.memory.mongo.MongoHistoryStore``
（构造注入 url / db / collection），而非依赖模块级单例函数。
"""

from typing import Any, Dict, List, Optional

from agent_core.memory.mongo import MongoHistoryStore
from app.core.config import settings

# 模块级单例（懒加载），保持与原 get_history_mongo_tool 行为一致。
_store: Optional[MongoHistoryStore] = None


def _get_store() -> MongoHistoryStore:
    global _store
    if _store is None:
        _store = MongoHistoryStore(settings.mongo_url, settings.mongo_db_name)
    return _store


def save_chat_message(
    session_id: str,
    role: str,
    text: str,
    rewritten_query: str = "",
    item_names: Optional[List[str]] = None,
    image_urls: Optional[List[str]] = None,
    message_id: Optional[str] = None,
) -> str:
    """写入/更新单条会话记录（兼容原签名，item_names/image_urls 透传扩展字段）。"""
    extras: Dict[str, Any] = {}
    if item_names is not None:
        extras["item_names"] = item_names
    if image_urls is not None:
        extras["image_urls"] = image_urls
    return _get_store().save(
        session_id,
        role,
        text,
        rewritten_query=rewritten_query,
        message_id=message_id,
        **extras,
    )


def get_recent_messages(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """查询指定会话最近 ``limit`` 条记录（时间正序）。"""
    return _get_store().get_recent(session_id, limit=limit)


def clear_history(session_id: str) -> int:
    """清空指定会话的全部历史，返回删除条数。"""
    return _get_store().clear(session_id)


def update_message_item_names(ids: List[str], item_names: List[str]) -> int:
    """批量回写关联商品名称。"""
    return _get_store().update_many(ids, item_names=item_names)


__all__ = [
    "save_chat_message",
    "get_recent_messages",
    "clear_history",
    "update_message_item_names",
    "MongoHistoryStore",
]
