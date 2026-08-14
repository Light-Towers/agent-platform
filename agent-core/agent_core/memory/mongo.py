# -*- coding: utf-8 -*-
"""
MongoDB 会话历史存储（框架无关内核，源自 zhiku mongo_history_utils）。

- ``MongoHistoryStore(url, db_name, collection)``：**构造注入**连接配置，去除对宿主
  ``settings`` 单例的硬依赖（DSH 集成只需传入自己的连接串）。
- schema 收敛最小字段 ``{session_id, role, text, ts}``；宿主专属字段（如 item_names /
  image_urls / rewritten_query）通过 ``save(**extras)`` / ``update(**extras)`` 透传扩展，
  由宿主侧决定，内核不绑定具体业务。
- 实现 ``ConversationMemory`` 协议；删除原 ``__main__`` 硬编码测试块。

需要 pymongo（``memory-mongo`` extra）；导入本模块前请先安装 pymongo。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from agent_core.logging import get_logger

logger = get_logger(__name__)


class MongoHistoryStore:
    """基于原生 PyMongo 的对话历史读写工具（构造注入，无 settings 依赖）。"""

    def __init__(self, mongo_url: str, db_name: str, collection: str = "chat_message") -> None:
        # pymongo 为可选依赖：懒导入，缺包时给出明确错误。
        try:
            from pymongo import MongoClient, ASCENDING, DESCENDING
            from bson import ObjectId
        except Exception as e:  # pragma: no cover - 依赖缺失路径
            raise ImportError(
                "pymongo 未安装；请安装 agent-core[memory-mongo]（uv sync --extra memory-mongo）"
            ) from e

        self._ObjectId = ObjectId
        self._ASCENDING = ASCENDING
        self._DESCENDING = DESCENDING
        try:
            self.client = MongoClient(mongo_url)
            self.db = self.client[db_name]
            self.collection = self.db[collection]
            # 复合索引：session_id 升序 + ts 降序，适配"按会话查最新记录"；幂等。
            self.collection.create_index([("session_id", 1), ("ts", -1)])
            logger.info("Successfully connected to MongoDB: %s", db_name)
        except Exception as e:
            logger.error("Failed to connect to MongoDB: %s", e)
            raise

    def save(
        self,
        session_id: str,
        role: str,
        text: str,
        rewritten_query: str = "",
        message_id: Optional[str] = None,
        **extras: Any,
    ) -> str:
        """写入/更新单条会话记录（最小 schema + 透传扩展字段）。

        :return: 新增返回 ObjectId 字符串，更新返回传入 message_id。
        """
        ts = datetime.now().timestamp()
        document = {
            "session_id": session_id,
            "role": role,
            "text": text,
            "rewritten_query": rewritten_query or "",
            "ts": ts,
        }
        # 透传宿主专属扩展字段（item_names / image_urls 等），内核不预定义。
        for k, v in extras.items():
            if v is not None:
                document[k] = v

        if message_id:
            self.collection.update_one(
                {"_id": self._ObjectId(message_id)},
                {"$set": document},
            )
            return message_id
        result = self.collection.insert_one(document)
        return str(result.inserted_id)

    def get_recent(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """查询指定会话最近 ``limit`` 条记录（按 ts 升序返回），失败返回空列表。"""
        try:
            cursor = (
                self.collection.find({"session_id": session_id})
                .sort("ts", self._DESCENDING)
                .limit(limit)
            )
            rows = list(cursor)
            rows.reverse()
            return rows
        except Exception as e:
            logger.error("Error getting recent messages: %s", e)
            return []

    def clear(self, session_id: str) -> int:
        """清空指定会话的全部历史，返回删除条数；失败返回 0。"""
        try:
            result = self.collection.delete_many({"session_id": session_id})
            logger.info("Deleted %s messages for session %s", result.deleted_count, session_id)
            return result.deleted_count
        except Exception as e:
            logger.error("Error clearing history for session %s: %s", session_id, e)
            return 0

    def update(self, message_id: str, **kwargs: Any) -> int:
        """按主键更新一条记录的指定字段，返回更新条数；失败返回 0。"""
        try:
            result = self.collection.update_one(
                {"_id": self._ObjectId(message_id)},
                {"$set": kwargs},
            )
            return result.modified_count
        except Exception as e:
            logger.error("Error updating history message %s: %s", message_id, e)
            return 0

    def update_many(self, ids: List[str], **kwargs: Any) -> int:
        """按主键列表批量更新字段（如回写 item_names），返回更新条数；失败返回 0。"""
        try:
            object_ids = [self._ObjectId(i) for i in ids]
            result = self.collection.update_many(
                {"_id": {"$in": object_ids}},
                {"$set": kwargs},
            )
            logger.info("Updated %s records with %s", result.modified_count, list(kwargs))
            return result.modified_count
        except Exception as e:
            logger.error("Error updating history messages: %s", e)
            return 0

    def close(self) -> None:
        """关闭 MongoDB 连接，释放连接池资源。"""
        try:
            self.client.close()
            logger.info("MongoDB connection closed")
        except Exception as e:
            logger.error("Error closing MongoDB connection: %s", e)


__all__ = ["MongoHistoryStore"]
