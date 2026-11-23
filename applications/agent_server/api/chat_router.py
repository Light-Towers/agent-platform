# -*- coding: utf-8 -*-
"""会话内图片上传端点（plan-image-qa-fullstack §刀3）。

与 /kb/uploads 不同：这里只存图到 PG（chat_images），**不触发知识库导入管线**，
不要求 knowledge_id。上传成功返回不透明 image_ref，后续 /query 用 context.images 携带。
"""

from __future__ import annotations

from agent_core.guardrails.errors import AppError
from agent_core.logging import get_logger
from agent_runtime.workspace_registry import server_tenant_id
from fastapi import APIRouter, Depends, File, UploadFile

from agent_server import chat_images as _store
from agent_server.api.auth import require_feature, verify_api_key
from agent_server.config import get_settings

router = APIRouter()
logger = get_logger(__name__)


@router.post("/chat/upload-image")
async def upload_chat_image(
    file: UploadFile = File(...),
    session_id: str = "",
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("chat.run")),
):
    """上传单张图片，返回 image_ref。鉴权 401 先于 403（与 /query 同口径）。"""
    settings = get_settings()
    tenant = server_tenant_id(settings.default_tenant_id)
    ext = _store.ext_for_content_type(file.content_type or "")
    if ext is None:
        raise AppError(415, "IMAGE_TYPE_UNSUPPORTED", "仅支持 png/jpeg/webp/gif")
    content = await file.read()
    if not content:
        raise AppError(400, "IMAGE_EMPTY", "图片内容为空")
    if len(content) > settings.chat_image_max_bytes:
        raise AppError(413, "IMAGE_TOO_LARGE", "图片超过大小上限")
    if not session_id:
        raise AppError(400, "SESSION_ID_REQUIRED", "缺少 session_id")

    ref = _store.make_ref(tenant, session_id, ext)
    try:
        await _store.save_image(ref, tenant, session_id, content, file.content_type or f"image/{ext}")
    except Exception:  # noqa: BLE001 — 存储故障统一降级为可读错误，异常全貌入日志
        logger.warning("chat image store failed: ref=%s", ref, exc_info=True)
        raise AppError(503, "IMAGE_STORE_FAILED", "图片存储失败")
    return {"image_ref": ref}
