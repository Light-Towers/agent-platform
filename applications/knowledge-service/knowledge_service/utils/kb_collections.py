# -*- coding: utf-8 -*-
"""知识库注册表（P1，plan-kb-delete-and-management-2026-11-18）。

**为什么需要这张表**：此前"知识库"只是从 kb_upload_history 按 knowledge_id 聚合出的
视图，没有一等实体 ⇒「整库删」「库下有文档禁删」两个判据无根（见 spec §0/D4）。
本模块用 Mongo collection ``kb_collections`` 把每个知识库登记成一行，知识库拥有独立的
生命周期（active/deleted），文档通过 knowledge_id 逻辑关联。

三条边界（决定，非默认）：
- **唯一键 = (tenant_id, knowledge_id)**：与 kb_documents 同口径；ensure_collection 幂等
  （已存在则只刷新 updated_at，不覆盖 owner/created_at）。
- **状态 active/deleted**：deleted = 软删除标记（P3 删除端点用）；本模块不物理删数据。
- **写失败不拦上传**：注册表是管理面/判据依据，不是 upload 闸门；Mongo 不可达只 WARNING
  （与 kb_registry/kb_upload_history 同纪律，避免上传链路多一个单点）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import PyMongoError

from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger

_COLLECTION = "kb_collections"
_ST_ACTIVE = "active"
_ST_DELETED = "deleted"
_store: Any = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_collection() -> Any:
    """懒加载单例（与 kb_registry 同形；KS 无迁移链，索引在这里幂等创建）。"""
    global _store
    if _store is None:
        from pymongo import MongoClient

        # Mongo 不可达时快速失败（默认 serverSelectionTimeoutMS=30s 会拖慢上传热路径的
        # get_chunk_config）；读配置失败本就要回落到全局默认，快失败符合意图。
        client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=3000)
        db = client[settings.mongo_db_name]
        col = db[_COLLECTION]
        col.create_index([("tenant_id", 1), ("knowledge_id", 1)], unique=True)
        col.create_index([("tenant_id", 1), ("updated_at", -1)])
        _store = col
    return _store


def ensure_collection(
    *,
    tenant_id: str,
    knowledge_id: str,
    name: str = "",
    owner: str = "",
    collection: Any = None,
) -> bool:
    """上传时幂等确保库存在。已存在只刷新 updated_at，不覆盖创建期字段。

    :return: 是否落库成功（失败 = False，调用方只落日志不抛）。
    """
    kid = str(knowledge_id or "").strip()
    tid = str(tenant_id or "").strip()
    if not kid or not tid:
        return False
    now = _now_iso()
    doc: Dict[str, Any] = {
        "tenant_id": tid,
        "knowledge_id": kid,
        "name": str(name or kid),
        "owner": str(owner or ""),
        "updated_at": now,
    }
    try:
        col = collection if collection is not None else _get_collection()
        col.update_one(
            {"tenant_id": tid, "knowledge_id": kid},
            {
                "$set": {"updated_at": now},
                "$setOnInsert": {
                    "name": doc["name"],
                    "owner": doc["owner"],
                    "status": _ST_ACTIVE,
                    "doc_count": 0,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        return True
    except PyMongoError as e:
        logger.warning(f"[kb_collections] 建库登记失败（上传不拦）: {e}")
        return False


def create_collection(
    *,
    tenant_id: str,
    name: str,
    owner: str = "",
    collection: Any = None,
) -> Dict[str, Any] | None:
    """新建知识库：系统生成全局唯一 knowledge_id（kb_<uuid4hex12>），存用户给的显示名。

    :return: {"knowledge_id","name",...} 成功；None = 写入失败。名字不查重（同名允许，
        ID 才唯一——成熟知识库平台也允许同名，靠 ID 区分）。
    """
    tid = str(tenant_id or "").strip()
    nm = str(name or "").strip()
    if not tid or not nm:
        return None
    import uuid

    kid = f"kb_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    doc = {
        "tenant_id": tid, "knowledge_id": kid, "name": nm, "owner": str(owner or ""),
        "status": _ST_ACTIVE, "doc_count": 0, "created_at": now, "updated_at": now,
    }
    try:
        col = collection if collection is not None else _get_collection()
        col.insert_one(dict(doc))
        doc.pop("_id", None)
        return doc
    except PyMongoError as e:
        logger.warning(f"[kb_collections] 新建知识库失败: {e}")
        return None


def rename_collection(
    tenant_id: str, knowledge_id: str, name: str, collection: Any = None
) -> bool:
    """改知识库显示名（不改 knowledge_id 主键）。返回是否命中一行。"""
    nm = str(name or "").strip()
    if not nm:
        return False
    try:
        col = collection if collection is not None else _get_collection()
        res = col.update_one(
            {"tenant_id": tenant_id, "knowledge_id": knowledge_id, "status": _ST_ACTIVE},
            {"$set": {"name": nm, "updated_at": _now_iso()}},
        )
        return bool(getattr(res, "matched_count", 0))
    except PyMongoError as e:
        logger.warning(f"[kb_collections] 改名失败: {e}")
        return False


def get_chunk_config(
    tenant_id: str, knowledge_id: str, collection: Any = None
) -> Optional[Dict[str, Any]]:
    """读库的切分配置（chunk_config 子文档）；库不存在或未配置返回 None。

    Mongo 不可达只 WARNING 不抛（与模块"写失败不拦上传"同纪律）——兜底逻辑见调用方。
    """
    try:
        col = collection if collection is not None else _get_collection()
        doc = col.find_one(
            {"tenant_id": tenant_id, "knowledge_id": knowledge_id, "status": _ST_ACTIVE},
            {"chunk_config": 1, "_id": 0},
        )
        return (doc or {}).get("chunk_config")
    except PyMongoError as e:
        logger.warning(f"[kb_collections] 读 chunk_config 失败（回落到默认）: {e}")
        return None


def update_chunk_config(
    tenant_id: str, knowledge_id: str, chunk_config: Dict[str, Any], collection: Any = None
) -> bool:
    """写库的切分配置（chunk_config 子文档 + updated_at）。返回是否命中 active 行。

    Mongo 不可达只 WARNING 不抛——配置写失败由上层接口决定如何回告。
    """
    try:
        col = collection if collection is not None else _get_collection()
        res = col.update_one(
            {"tenant_id": tenant_id, "knowledge_id": knowledge_id, "status": _ST_ACTIVE},
            {"$set": {"chunk_config": dict(chunk_config), "updated_at": _now_iso()}},
        )
        return bool(getattr(res, "matched_count", 0))
    except PyMongoError as e:
        logger.warning(f"[kb_collections] 写 chunk_config 失败: {e}")
        return False


def get(tenant_id: str, knowledge_id: str, collection: Any = None) -> Optional[Dict[str, Any]]:
    """按 (tenant, knowledge_id) 取库记录；无则 None。"""
    col = collection if collection is not None else _get_collection()
    return col.find_one({"tenant_id": tenant_id, "knowledge_id": knowledge_id}, {"_id": 0})


def list_by_tenant(
    tenant_id: str, *, limit: int = 100, include_deleted: bool = False, collection: Any = None
) -> List[Dict[str, Any]]:
    """列出租户的知识库（updated_at 降序）；默认排除 deleted。"""
    col = collection if collection is not None else _get_collection()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if not include_deleted:
        query["status"] = _ST_ACTIVE
    cursor = col.find(query, {"_id": 0}).sort("updated_at", -1).limit(limit)
    return list(cursor)


def mark_deleted(
    tenant_id: str, knowledge_id: str, collection: Any = None
) -> bool:
    """P3 用：把库标记 deleted（软删除，不物理删）。返回是否命中一行。"""
    try:
        col = collection if collection is not None else _get_collection()
        res = col.update_one(
            {"tenant_id": tenant_id, "knowledge_id": knowledge_id, "status": _ST_ACTIVE},
            {"$set": {"status": _ST_DELETED, "updated_at": _now_iso()}},
        )
        return bool(getattr(res, "matched_count", 0))
    except PyMongoError as e:
        logger.warning(f"[kb_collections] 库删除标记失败: {e}")
        return False


__all__ = ["ensure_collection", "create_collection", "rename_collection", "get_chunk_config", "update_chunk_config", "get", "list_by_tenant", "mark_deleted", "STATUS_ACTIVE", "STATUS_DELETED"]

# 状态常量以公开名导出（P3 删除端点/判据用）
STATUS_ACTIVE = _ST_ACTIVE
STATUS_DELETED = _ST_DELETED
