# -*- coding: utf-8 -*-
"""知识库上传历史（持久化，批 4 新增）。

**为什么需要这张表**：``task_utils.py`` 的任务状态/切块读数全是进程内存 dict（重启即失），
``kb_registry.py`` 的 ``kb_documents`` 又只登记填了 ``knowledge_id`` 的上传（默认上传留空
⇒ 不登记）。结果是「昨天传过什么、怎么切的」刷新/重启后全丢，前端只能把读数存浏览器
localStorage（换设备/清缓存仍丢）。本模块用 Mongo collection ``kb_upload_history`` 把
**每次上传一行**持久化，唯一键 = ``task_id``，前端从服务端拉历史。

三条边界（每条都是决定）：
- **唯一键 = task_id**：每次上传一行；同 task_id 再写 = 覆盖（后台管线补写状态/summary）。
- **落库点在 run_graph_task 尾部**：summary 是管线中途才产出的，HTTP handler 执行时还没有；
  在管线结束后同时写状态/summary/error 才拿得齐。
- **存储写失败不拦上传**：历史是观测面、不是 upload 闸门；Mongo 不可达只 WARNING。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import PyMongoError

from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger

_COLLECTION = "kb_upload_history"
_store: Any = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_collection() -> Any:
    """懒加载单例（与 kb_registry 同形；KS 无迁移链，索引在这里幂等创建）。"""
    global _store
    if _store is None:
        from pymongo import MongoClient

        client = MongoClient(settings.mongo_url)
        db = client[settings.mongo_db_name]
        col = db[_COLLECTION]
        # task_id 唯一（每次上传一行）；tenant+uploaded_at 复合供列表排序走索引。
        col.create_index([("task_id", 1)], unique=True)
        col.create_index([("tenant_id", 1), ("uploaded_at", -1)])
        _store = col
    return _store


def record_upload(
    *,
    task_id: str,
    tenant_id: str,
    filename: str,
    metadata: Dict[str, Any],
    status: str,
    summary: Optional[Dict[str, Any]] = None,
    error: str = "",
    collection: Any = None,
) -> bool:
    """落一条上传历史（首次创建写 created_at，后续覆盖只更新动态字段）。

    :param status: 管线终态（completed / failed）
    :param summary: 切块读数（get_task_summary 的返回值，可能为空 —— 失败/观测缺失时诚实为空）
    :param error: 失败原因（成功时空串）
    """
    if not task_id:
        return False
    now = _now_iso()
    doc: Dict[str, Any] = {
        "task_id": task_id,
        "tenant_id": tenant_id,
        "filename": filename,
        "knowledge_id": str(metadata.get("knowledge_id", "") or ""),
        "scope_type": str(metadata.get("scope_type", "") or ""),
        "metadata": dict(metadata),
        "status": status,
        "summary": dict(summary or {}),
        "error": error,
        "updated_at": now,
    }
    try:
        col = collection if collection is not None else _get_collection()
        col.update_one(
            {"task_id": task_id},
            {"$set": doc, "$setOnInsert": {"created_at": now, "uploaded_at": now}},
            upsert=True,
        )
        return True
    except PyMongoError as e:  # 连接/写失败按"没记成历史"处理，不拦上传
        logger.warning(f"[kb_upload_history] 历史落库失败（上传不受影响）: {e}")
        return False


def list_by_tenant(tenant_id: str, *, limit: int = 100, collection: Any = None) -> List[Dict[str, Any]]:
    """列出租户的上传历史（uploaded_at 降序，最新在前）；exclude _id。"""
    col = collection if collection is not None else _get_collection()
    cursor = (
        col.find({"tenant_id": tenant_id}, {"_id": 0})
        .sort("uploaded_at", -1)
        .limit(limit)
    )
    return list(cursor)


__all__ = ["record_upload", "list_by_tenant"]
