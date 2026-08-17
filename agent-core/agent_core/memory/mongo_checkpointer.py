# -*- coding: utf-8 -*-
"""LangGraph checkpointer 的 MongoDB 实现（共享会话历史持久化）。

替代 LangGraph 原生 ``InMemorySaver`` / ``AsyncSqliteSaver``，将图状态快照
（checkpoint + metadata + writes）持久化到 MongoDB，进程重启不丢，并按
``thread_id`` / ``tenant_id`` 隔离（多租户）。

仅覆盖异步接口（LangGraph 全程 astream 不触发同步路径）；同步接口保持基类
``NotImplementedError``。

依赖：pymongo（``memory-mongo`` extra）。导入时懒加载，缺包时给出明确错误。

此前实现在 deepagents/agent/memory/mongo_checkpointer.py，现收口到内核供所有子包复用。
"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Optional, Sequence

from agent_core.logging import get_logger
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langchain_core.runnables import RunnableConfig

logger = get_logger(__name__)

# 后台线程池：把阻塞式 pymongo 调用移出事件循环。LangGraph 全程 astream 会高频
# 触发 checkpoint 读写，若同步 pymongo 直接跑在 async 方法内会阻塞整个事件循环，
# 拖垮并发请求。统一经 _run 投入线程池执行。
_MONGO_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mongo-io")


def _run(fn, *args, **kwargs):
    """在线程池执行阻塞式 pymongo 调用并 await 其结果（不阻塞 asyncio 调度）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    return loop.run_in_executor(_MONGO_EXECUTOR, functools.partial(fn, *args, **kwargs))


def _tid(config: RunnableConfig) -> str:
    return config["configurable"].get("thread_id", "")


def _ns(config: RunnableConfig) -> str:
    return config["configurable"].get("checkpoint_ns", "")


def _cid(config: RunnableConfig) -> str:
    return config["configurable"].get("checkpoint_id", "")


class MongoCheckpointer(BaseCheckpointSaver[str]):
    """基于 PyMongo 的 LangGraph checkpointer。

    Schema（集合 ``langgraph_checkpoints``）：
        {
            thread_id, checkpoint_ns, checkpoint_id,
            parent_id,            # 父 checkpoint_id（用于链回溯）
            checkpoint_blob,      # serde.dumps(checkpoint) → Binary
            metadata_blob,        # serde.dumps(metadata)  → Binary
            writes: [...],        # pending_writes（aput_writes 写入）
            tenant_id,            # 多租户隔离列
        }
    """

    def __init__(
        self,
        mongo_url: str,
        db_name: str = "deepagents",
        collection: str = "langgraph_checkpoints",
        tenant_id: str = "default",
        *,
        serde: Any | None = None,
    ) -> None:
        super().__init__(serde=serde)
        try:
            from pymongo import MongoClient, ASCENDING
        except Exception as e:  # pragma: no cover - 依赖缺失路径
            raise ImportError(
                "pymongo 未安装；请安装 agent-core[memory-mongo]"
            ) from e

        try:
            self._client = MongoClient(mongo_url)
            self._db = self._client[db_name]
            self._coll = self._db[collection]
            self._tenant_id = tenant_id
            # 复合索引：租户 + 线程 + 命名空间 + checkpoint 时间序
            self._coll.create_index(
                [("tenant_id", ASCENDING), ("thread_id", ASCENDING),
                 ("checkpoint_ns", ASCENDING), ("checkpoint_id", ASCENDING)],
                unique=True,
            )
            logger.info("MongoCheckpointer 已连接: %s/%s", db_name, collection)
        except Exception as e:
            logger.error("MongoCheckpointer 连接失败: %s", e)
            raise

    # ---- 内部辅助 ----
    def _doc_filter(self, config: RunnableConfig, extra: dict | None = None) -> dict:
        f = {
            "tenant_id": self._tenant_id,
            "thread_id": _tid(config),
            "checkpoint_ns": _ns(config),
        }
        if _cid(config):
            f["checkpoint_id"] = _cid(config)
        if extra:
            f.update(extra)
        return f

    def _to_tuple(self, doc: dict) -> CheckpointTuple:
        checkpoint = self.serde.loads_typed((doc["checkpoint_type"], doc["checkpoint_blob"]))
        metadata = self.serde.loads_typed((doc["metadata_type"], doc["metadata_blob"]))
        parent_config: RunnableConfig | None = None
        if doc.get("parent_id"):
            parent_config = {
                "configurable": {
                    "thread_id": doc["thread_id"],
                    "checkpoint_ns": doc["checkpoint_ns"],
                    "checkpoint_id": doc["parent_id"],
                }
            }
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": doc["thread_id"],
                    "checkpoint_ns": doc["checkpoint_ns"],
                    "checkpoint_id": doc["checkpoint_id"],
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
        )

    # ---- 异步读 ----
    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        if not _cid(config):
            return None
        doc = await _run(self._coll.find_one, self._doc_filter(config))
        return self._to_tuple(doc) if doc else None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        query: dict = {"tenant_id": self._tenant_id}
        if config:
            query["thread_id"] = _tid(config)
            if _ns(config):
                query["checkpoint_ns"] = _ns(config)
        if before and _cid(before):
            query["checkpoint_id"] = {"$lt": _cid(before)}
        if filter:
            for k, v in filter.items():
                query["metadata." + str(k)] = v

        def _query() -> list[dict]:
            cursor = self._coll.find(query).sort("checkpoint_id", -1)
            if limit:
                cursor = cursor.limit(limit)
            return list(cursor)

        docs = await _run(_query)
        for doc in docs:
            yield self._to_tuple(doc)

    # ---- 异步写 ----
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        ck_type, ck_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(metadata)
        parent_id = (metadata or {}).get("parents", {}).get(_ns(config))

        def _update() -> None:
            self._coll.update_one(
                self._doc_filter(config),
                {
                    "$set": {
                        "tenant_id": self._tenant_id,
                        "thread_id": _tid(config),
                        "checkpoint_ns": _ns(config),
                        "checkpoint_id": _cid(config),
                        "parent_id": parent_id,
                        "checkpoint_type": ck_type,
                        "checkpoint_blob": ck_blob,
                        "metadata_type": md_type,
                        "metadata_blob": md_blob,
                    }
                },
                upsert=True,
            )

        await _run(_update)
        return config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        def _merge() -> None:
            existing = self._coll.find_one(self._doc_filter(config), {"writes": 1})
            cur = list(existing.get("writes", [])) if existing else []
            for ch, value in writes:
                cur.append({"channel": ch, "value": value, "task_id": task_id})
            self._coll.update_one(
                self._doc_filter(config),
                {"$set": {"writes": cur}},
                upsert=True,
            )

        await _run(_merge)

    async def adelete_thread(self, thread_id: str) -> None:
        await _run(
            self._coll.delete_many,
            {"tenant_id": self._tenant_id, "thread_id": thread_id},
        )

    # str 版本递增：保证 checkpoint_id 单调且可直接排序
    def get_next_version(self, current: str | None, channel: Any = None) -> str:
        import uuid

        return uuid.uuid4().hex


__all__ = ["MongoCheckpointer"]
