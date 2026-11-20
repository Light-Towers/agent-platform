# -*- coding: utf-8 -*-
"""知识文档注册表（批 2a 新增；方案补记 9 的 KS 侧设计落地）。

**为什么需要这张表**：``/upload`` 的 ``knowledge_id``/``status`` 等元数据只活在
LangGraph state（进程内）与 chunk 标量字段里，**没有任何持久化的 knowledge_id↔文档
映射**——``task_utils.py`` 纯内存（重启即失）、Milvus 里只有 PUBLISHED 文档的 chunk。
「按 knowledge_id 重提入库」（``/reimport``，kb.publish 的 KS 上游）因此没有可查的
依据 ⇒ 本模块用 Mongo collection ``kb_documents`` 把每次上传登记成一行。

三条边界（每条都是决定，不是默认）：
- **唯一键 = (tenant_id, knowledge_id)**：同键再传 = upsert（新 task 覆盖旧记录，
  旧任务目录不清理——清理属运维面，本批不做）。
- **knowledge_id 为空的上传不登记**：既有行为保持不变；未登记文档不可重提、不出现在
  ``/documents`` 列表（诚实降级，不是静默丢——``/upload`` 侧对该情况有 INFO 日志）。
- **存储写失败不拦上传**：registry 是 publish 的前提、不是 upload 的闸门；Mongo 不可达
  时上传照常成功（返回 task_ids），只落 WARNING——否则聊天历史那个 Mongo 依赖会把
  整条上传链路变成单点。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# pymongo 是 KS 硬依赖（pyproject dependencies），异常层级顶层 here 收窄用：
# 连接失败（ConnectionFailure/ServerSelection）/ 索引与写失败（OperationFailure）
# 都是 PyMongoError 子类 —— 宽捕收窄为这一族；序列化错误（bson.errors.InvalidDocument）
# 刻意**不**吞：那是编程错误，静默吞掉 = 注册表静默丢数据，比 500 更糟。
from pymongo.errors import PyMongoError

from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger

_COLLECTION = "kb_documents"
_store: Any = None


def _now_iso() -> str:
    """UTC ISO 时间戳（无本地时区歧义；审计与排序都用它）。"""
    return datetime.now(timezone.utc).isoformat()


def _get_collection() -> Any:
    """懒加载单例（与 mongo_history_utils 同形：pymongo 缺包/连不上时给明确错误）。

    集合名与唯一索引在这里创建（幂等）：KS 无迁移链（方案 §5 F22 实取），
    collection 与索引定义只能进启动装配路径——本函数就是那条路径（首个调用点）。
    """
    global _store
    if _store is None:
        from pymongo import MongoClient

        client = MongoClient(settings.mongo_url)
        db = client[settings.mongo_db_name]
        col = db[_COLLECTION]
        # 唯一索引 (tenant_id, knowledge_id)：同键 upsert 的物理保证，不是应用层约定。
        col.create_index([("tenant_id", 1), ("knowledge_id", 1)], unique=True)
        _store = col
    return _store


def upsert_by_upload(
    *,
    tenant_id: str,
    knowledge_id: str,
    scope_type: str,
    task_id: str,
    filename: str,
    local_dir: str,
    local_file_path: str,
    minio_object: str,
    metadata: Dict[str, Any],
    status: str,
    collection: Any = None,
) -> bool:
    """登记/覆盖一条上传记录。返回是否落库成功（失败 = False，调用方只落日志不抛）。"""
    if not knowledge_id.strip():
        return False
    doc: Dict[str, Any] = {
        "knowledge_id": knowledge_id,
        "tenant_id": tenant_id,
        "scope_type": scope_type,
        "task_id": task_id,
        "filename": filename,
        "local_dir": local_dir,
        "local_file_path": local_file_path,
        "minio_object": minio_object,
        "metadata": dict(metadata),
        "status": status,
        "updated_at": _now_iso(),
    }
    try:
        col = collection if collection is not None else _get_collection()
        col.update_one(
            {"tenant_id": tenant_id, "knowledge_id": knowledge_id},
            {
                "$set": doc,
                "$setOnInsert": {"created_at": doc["updated_at"]},
            },
            upsert=True,
        )
        return True
    except PyMongoError as e:  # 连接/索引/写失败都按"没登记"处理；编程错误（序列化）如实抛
        logger.warning(f"[kb_registry] 登记失败（上传不受影响，该条不可重提）: {e}")
        return False


def get_document(tenant_id: str, knowledge_id: str, collection: Any = None) -> Optional[Dict[str, Any]]:
    """按 (tenant, knowledge_id) 取一条记录；无则 None（调用方转 404，不静默回落）。"""
    col = collection if collection is not None else _get_collection()
    return col.find_one({"tenant_id": tenant_id, "knowledge_id": knowledge_id})


def list_by_tenant(tenant_id: str, *, limit: int = 100, collection: Any = None) -> List[Dict[str, Any]]:
    """列出租户的登记文档（updated_at 降序，最新在前）。limit 由调用方钳制。"""
    col = collection if collection is not None else _get_collection()
    cursor = (
        col.find({"tenant_id": tenant_id}, {"_id": 0})
        .sort("updated_at", -1)
        .limit(limit)
    )
    return list(cursor)


def update_status(
    *,
    tenant_id: str,
    knowledge_id: str,
    status: str,
    task_id: str,
    collection: Any = None,
) -> bool:
    """重提后回写状态与最新 task_id。失败只落日志（状态以重提响应为准，不阻塞主流程）。"""
    try:
        col = collection if collection is not None else _get_collection()
        col.update_one(
            {"tenant_id": tenant_id, "knowledge_id": knowledge_id},
            {"$set": {"status": status, "task_id": task_id, "updated_at": _now_iso()}},
        )
        return True
    except PyMongoError as e:
        logger.warning(f"[kb_registry] 状态回写失败: {e}")
        return False


def delete_document(
    tenant_id: str, knowledge_id: str, collection: Any = None,
) -> bool:
    """真删除登记行（purge 用）。失败只落日志，返回是否成功。"""
    try:
        col = collection if collection is not None else _get_collection()
        result = col.delete_one({"tenant_id": tenant_id, "knowledge_id": knowledge_id})
        return (result.deleted_count or 0) > 0
    except PyMongoError as e:
        logger.warning(f"[kb_registry] 登记删除失败: {e}")
        return False


__all__ = ["upsert_by_upload", "get_document", "list_by_tenant", "update_status", "delete_document"]
