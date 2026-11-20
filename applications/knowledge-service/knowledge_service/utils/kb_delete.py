# -*- coding: utf-8 -*-
"""知识库软删除逻辑（P3，plan-kb-delete-and-management-2026-11-18）。

删除语义（用户拍板）：软删除，数据可恢复。
- **删单文档**：把该 knowledge_id 的 Milvus 切片 status 改成 REVOKED（检索谓词
  `status != REVOKED` 自然排除）。pymilvus 无原地 update ⇒ 读全部切片（向量原样）→
  删旧 → 用 REVOKED 重插。同步把 kb_documents 该行状态改 REVOKED。
- **删整库**：前置校验"库下无有效文档"（所有关联文档都 REVOKED）才允许；通过后把
  kb_collections 该行标 deleted。

三条边界（决定，非默认）：
- **不物理删向量/文件**：REVOKED 切片永久保留（可恢复），只是检索不再召回。
- **tenant 安全边界**：所有操作按 (tenant_id, knowledge_id) 定位，跨租户删不到。
- **可逆**：REVOKED 可通过重新发布（DRAFT→...→PUBLISHED）恢复；库 deleted 可重新建。

模块无 KS 硬依赖（client / registry / collections 全注入缝），零 Milvus/Mongo 可单测。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

# 状态值（与 shared_schemas.knowledge_lifecycle.KNOWLEDGE_STATUS 对齐；本模块零 KS 依赖故用字面量）
REVOKED = "REVOKED"
PUBLISHED = "PUBLISHED"
# 读切片时必须带出的字段（含向量，重插时原样复用；chunk_id 主键不复用）
_READ_FIELDS = (
    "content", "title", "parent_title", "part", "file_title", "item_name",
    "tenant_id", "scope_type", "knowledge_id", "workspace_id", "status",
    "embedding_model", "chunk_version", "created_at", "source_doc",
    "dense_vector", "sparse_vector",
)


def read_chunks(
    client: Any, collection: str, tenant_id: str, knowledge_id: str,
    *, source_doc: str | None = None,
) -> List[Dict[str, Any]]:
    """读该 (tenant, knowledge_id) 的切片（含向量）。source_doc 给定时只读该文档。"""
    expr = f'tenant_id == "{tenant_id}" and knowledge_id == "{knowledge_id}"'
    if source_doc is not None:
        expr += f' and source_doc == "{source_doc}"'
    return list(client.query(
        collection_name=collection, filter=expr,
        output_fields=list(_READ_FIELDS), limit=16384,
    ) or [])


def has_other_active_docs(
    client: Any, collection: str, tenant_id: str, knowledge_id: str, source_doc: str,
) -> bool:
    """该库是否还有「除 source_doc 外」的非 REVOKED 切片——决定是否回写登记表。"""
    rows = client.query(
        collection_name=collection,
        filter=(
            f'tenant_id == "{tenant_id}" and knowledge_id == "{knowledge_id}" '
            f'and status != "{REVOKED}" and source_doc != "{source_doc}"'
        ),
        output_fields=["chunk_id"], limit=1,
    ) or []
    return len(rows) > 0


def _delete_chunks(
    client: Any, collection: str, tenant_id: str, knowledge_id: str,
    source_doc: str | None,
) -> int:
    """按 (tenant, kid[, source_doc]) 严格定位删 Milvus 切片，返回删前读到的条数。"""
    rows = read_chunks(client, collection, tenant_id, knowledge_id, source_doc=source_doc)
    if not rows:
        return 0
    delete_expr = f'tenant_id == "{tenant_id}" and knowledge_id == "{knowledge_id}"'
    if source_doc is not None:
        delete_expr += f' and source_doc == "{source_doc}"'
    client.delete(collection_name=collection, filter=delete_expr)
    return len(rows)


def _reinsert_with_status(
    client: Any, collection: str, rows: List[Dict[str, Any]], status: str,
) -> int:
    """把读到的切片用目标 status 重插（向量原样复用，去主键让 auto_id 重生成），返回条数。"""
    to_insert = []
    for r in rows:
        item = {k: r[k] for k in _READ_FIELDS if k in r}
        item.pop("chunk_id", None)
        item["status"] = status
        to_insert.append(item)
    if to_insert:
        client.insert(collection_name=collection, data=to_insert)
    return len(to_insert)


def revoke_document(
    client: Any, collection: str, tenant_id: str, knowledge_id: str,
    *, source_doc: str | None = None,
    update_registry: Callable[[str, str, str], bool] | None = None,
) -> Dict[str, Any]:
    """软删除（下线）：切片 status→REVOKED。source_doc 给定时只下线该文档，否则下线整库。"""
    rows = read_chunks(client, collection, tenant_id, knowledge_id, source_doc=source_doc)
    if not rows:
        return {"deleted_chunks": 0, "revoked_chunks": 0, "registry_updated": False, "found": False}

    _delete_chunks(client, collection, tenant_id, knowledge_id, source_doc)
    inserted = _reinsert_with_status(client, collection, rows, REVOKED)

    # 登记表回写：整库删必写；单文档删仅当其它文档均已 REVOKED 才写。
    registry_updated = False
    if update_registry is not None:
        still_has_docs = (
            has_other_active_docs(client, collection, tenant_id, knowledge_id, source_doc)
            if source_doc is not None else False
        )
        if not still_has_docs:
            registry_updated = bool(update_registry(tenant_id, knowledge_id, REVOKED))

    return {
        "deleted_chunks": len(rows), "revoked_chunks": inserted,
        "registry_updated": registry_updated, "found": True,
        "source_doc": source_doc or "",
    }


def restore_document(
    client: Any, collection: str, tenant_id: str, knowledge_id: str,
    *, source_doc: str,
    update_registry: Callable[[str, str, str], bool] | None = None,
) -> Dict[str, Any]:
    """重新上线：把该文档 REVOKED 切片改回 PUBLISHED（可被检索重新召回）。

    只处理确为 REVOKED 的切片；没有已下线切片则 found=False（幂等/防误操作）。
    登记表状态回写为 PUBLISHED（该库恢复有效）。
    """
    rows = read_chunks(client, collection, tenant_id, knowledge_id, source_doc=source_doc)
    if not any(str(r.get("status") or "").upper() == REVOKED for r in rows):
        # 没有已下线切片 ⇒ 不该上线（幂等/防误操作）
        return {"found": False, "restored_chunks": 0, "registry_updated": False}

    # 下线是整文档操作 ⇒ 该文档切片应全为 REVOKED；全部重插为 PUBLISHED。
    _delete_chunks(client, collection, tenant_id, knowledge_id, source_doc)
    inserted = _reinsert_with_status(client, collection, rows, PUBLISHED)
    registry_updated = False
    if update_registry is not None:
        registry_updated = bool(update_registry(tenant_id, knowledge_id, PUBLISHED))
    return {"found": True, "restored_chunks": inserted,
            "registry_updated": registry_updated, "source_doc": source_doc}


def purge_document(
    client: Any, collection: str, tenant_id: str, knowledge_id: str,
    *, source_doc: str,
    delete_registry: Callable[[str, str], bool] | None = None,
) -> Dict[str, Any]:
    """真删除（不可逆）：物理删该文档全部切片（含 REVOKED），并清 kb_documents 登记。

    与 revoke_document 的区别：只删不重插 ⇒ 数据彻底消失，文档树不再显示。
    """
    deleted = _delete_chunks(client, collection, tenant_id, knowledge_id, source_doc)
    # registry 清理是「附带」操作：切片已物理删除即达成用户目标。登记清理失败不该让
    # 整个删除报失败（用户视角：文档已删掉，不该看到"删除失败"）——失败只标记不抛。
    registry_deleted = False
    if delete_registry is not None:
        try:
            registry_deleted = bool(delete_registry(tenant_id, knowledge_id))
        except Exception:  # noqa: BLE001 — 附带清理失败不影响删除结果
            registry_deleted = False
    return {"found": deleted > 0, "deleted_chunks": deleted,
            "registry_deleted": registry_deleted, "source_doc": source_doc}


def has_active_documents(
    tenant_id: str, knowledge_id: str,
    *, list_by_tenant: Callable[..., List[Dict[str, Any]]],
) -> bool:
    """整库删前置判据：该 knowledge_id 下是否还有非 REVOKED 的登记文档。

    kb_documents 一库一行（upsert），这里按 tenant 列出后按 knowledge_id 过滤状态。
    list_by_tenant 注入（KS kb_registry.list_by_tenant）。
    """
    rows = list_by_tenant(tenant_id, limit=100) or []
    for r in rows:
        if str(r.get("knowledge_id") or "").strip() != knowledge_id:
            continue
        status = str(r.get("status") or "").upper()
        if status and status != REVOKED:
            return True
    return False


def has_active_chunks(
    client: Any, collection: str, tenant_id: str, knowledge_id: str,
) -> bool:
    """整库删前置判据（2026-11-19 改）：该库 Milvus 里是否还有非 REVOKED 切片。

    与页面文档树同源。旧判据读 kb_documents 登记表 status，会与实际切片漂移——
    上传失败卡在 DRAFT/REVIEWING 的空壳库在页面看是无文档的，却被 409 拒绝删库。
    """
    rows = client.query(
        collection_name=collection,
        filter=(
            f'tenant_id == "{tenant_id}" and knowledge_id == "{knowledge_id}" '
            f'and status != "{REVOKED}"'
        ),
        output_fields=["chunk_id"], limit=1,
    ) or []
    return len(rows) > 0


def delete_collection_guard(
    tenant_id: str, knowledge_id: str,
    *, client: Any, collection: str,
    mark_deleted: Callable[[str, str], bool],
) -> Tuple[bool, str]:
    """整库删：前置校验 + 标记 deleted。返回 (是否成功, 原因/说明)。

    判据以 Milvus 实际有效切片为准（与页面文档树同源），不再读 kb_documents 登记表——
    避免"页面看着没文档却删不掉"的漂移。
    """
    if client is None:
        return (False, "Milvus 不可达，无法校验库下是否有有效文档")
    try:
        if has_active_chunks(client, collection, tenant_id, knowledge_id):
            return (False, "知识库下仍有有效文档（非 REVOKED），请先将文档全部下线后再删库")
    except Exception:  # noqa: BLE001 — fail-closed：校验不了就不让删，不误放行
        return (False, "有效文档校验失败，为安全起见暂不允许删库")
    ok = bool(mark_deleted(tenant_id, knowledge_id))
    if not ok:
        return (False, "知识库不存在或已被删除")
    return (True, "知识库已标记删除")


__all__ = ["REVOKED", "PUBLISHED", "read_chunks", "has_other_active_docs", "revoke_document", "restore_document", "purge_document", "has_active_documents", "has_active_chunks", "delete_collection_guard"]
