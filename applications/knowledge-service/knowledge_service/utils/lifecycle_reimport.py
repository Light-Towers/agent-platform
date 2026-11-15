# -*- coding: utf-8 -*-
"""重提入库的纯决策逻辑（批 2a）。

为什么单独成模块：``/reimport`` 端点住在 ``api/import_router.py``，而后者模块级
import ``main_graph``（LangGraph 全图编译 ⇒ langchain/magic-pdf/pymilvus 重型链）。
``tests/unit`` 套件**刻意零重型依赖**（unit conftest 头部契约，每次 PR 必跑）⇒
把可单测的决策面（迁移校验 / metadata 合并 / PUBLISHED 前置校验 / 原文定位）抽到
本模块，端点只留薄壳接线。

本模块的依赖面刻意收窄：shared_schemas（契约）+ settings/logger，**不 import
minio_utils**——那个模块 import 时会连 MinIO 试建桶（导入副作用），minio client
由调用方以参数注入。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from shared_schemas.knowledge_lifecycle import KNOWLEDGE_STATUS, VALID_TRANSITIONS, validate_metadata

from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger


class ReimportError(Exception):
    """重提决策阶段的具名拒绝：status_code + detail，由端点薄壳转 HTTPException。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def plan_reimport(
    record: Dict[str, Any],
    *,
    tenant_id: str,
    status: str,
    authority: str = "",
    effective_from: str = "",
    effective_to: str = "",
) -> Dict[str, Any]:
    """迁移校验 + metadata 合并 + PUBLISHED 前置校验；通过 ⇒ 返回覆写后的 metadata。

    :param record: kb_documents 登记行（含 status 与 metadata 13 字段）。
    :raises ReimportError: 400 —— 未知状态 / 非法迁移（VALID_TRANSITIONS）/
        PUBLISHED 缺必备项（逐条列缺项，shared_schemas.validate_metadata 口径）。
    """
    frm = record.get("status") or "DRAFT"
    try:
        s_from = KNOWLEDGE_STATUS(frm)
        s_to = KNOWLEDGE_STATUS(status)
    except ValueError:
        raise ReimportError(400, f"未知状态: {frm} 或 {status}") from None
    if (s_from, s_to) not in VALID_TRANSITIONS:
        raise ReimportError(
            400, f"非法迁移: {frm} → {status}（合法迁移表见 shared_schemas.knowledge_lifecycle）"
        )

    # 目标 PUBLISHED：metadata 必备项校验（三字段允许本次覆盖，空=沿用登记值）
    meta = dict(record.get("metadata") or {})
    meta.update(
        {
            "knowledge_id": record.get("knowledge_id", ""),
            "tenant_id": tenant_id,
            "status": status,
        }
    )
    for key, value in (("authority", authority), ("effective_from", effective_from), ("effective_to", effective_to)):
        if value.strip():
            meta[key] = value.strip()
    if s_to == KNOWLEDGE_STATUS.PUBLISHED:
        ok, errors = validate_metadata(meta)
        if not ok:
            raise ReimportError(400, f"PUBLISHED 前置校验失败：{'；'.join(errors)}")
    return meta


def resolve_original_file(
    record: Dict[str, Any],
    task_local_dir: str,
    minio_client: Optional[Any],
) -> str:
    """定位重提用的原文：本地路径在则用（不复制），不在则经注入的 minio client
    取回新任务目录（``fget_object``，同步——调用方放线程池）。

    :param minio_client: ``minio_utils.get_minio_client()`` 的产物；None = 初始化失败。
    :raises ReimportError: 409 —— 本地与对象存储都不在了（磁盘清理/桶回收）；
        502 —— 对象存储不可用或取回失败。
    """
    local_path = record.get("local_file_path") or ""
    if local_path and os.path.exists(local_path):
        return local_path
    minio_object = record.get("minio_object") or ""
    if not minio_object:
        raise ReimportError(409, "原文已不在（无本地文件且无对象存储记录），无法重提")
    if minio_client is None:
        raise ReimportError(502, "对象存储不可用，无法从备份恢复原文")
    filename = record.get("filename") or os.path.basename(minio_object.replace("\\", "/"))
    restored = os.path.join(task_local_dir, filename)
    try:
        minio_client.fget_object(settings.minio_bucket_name, minio_object, restored)
    except Exception as e:
        logger.error(f"从对象存储恢复原文失败: {e}", exc_info=True)
        raise ReimportError(502, "从对象存储恢复原文失败") from e
    return restored


__all__ = ["ReimportError", "plan_reimport", "resolve_original_file"]
