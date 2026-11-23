# -*- coding: utf-8 -*-
"""图片代理端点（plan-image-qa-fullstack D1=B）。

浏览器无法直连集群内的 ``minio:9000``（私有桶 + 集群内 DNS）。知识库切片里的图片链接
形如 ``http://minio:9000/kb-import-bucket/images/...``，前端把它改写到本端点
``/img/{bucket}/{object_path}``，由 agent_server 用 MinIO 凭证从私有桶取字节流式回浏览器。

安全：
- 与 /query 同款鉴权（verify_api_key → 401；require_feature("chat.run") → 403）。
- bucket 必须等于配置的桶（防任意桶枚举）；object_path 拒绝 ``..`` 绝对路径（防穿越）。
- 只透传图片 MIME（按扩展名白名单），不回显异常细节。
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from agent_core.guardrails.errors import AppError
from agent_core.logging import get_logger
from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response

from agent_server.api.auth import require_feature, verify_api_key
from agent_server.config import get_settings

logger = get_logger(__name__)
router = APIRouter()

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@lru_cache(maxsize=1)
def _get_minio_client():
    """进程级单例 MinIO 客户端（复用 KS minio_utils 的建法）。凭证未配返回 None。"""
    from minio import Minio

    s = get_settings()
    if not s.minio_access_key or not s.minio_secret_key:
        return None
    return Minio(
        endpoint=s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
    )


def _safe_object_path(object_path: str) -> str | None:
    """校验对象路径：拒绝绝对路径/..穿越/空段。合法返回原路径。"""
    if not object_path or object_path.startswith("/") or "\\" in object_path:
        return None
    parts = object_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return object_path


@router.get("/img/{bucket}/{object_path:path}")
async def proxy_image(
    bucket: str,
    object_path: str = Path(...),
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("chat.run")),
):
    """从私有 MinIO 桶取图片字节，流式回浏览器。"""
    settings = get_settings()
    if bucket != settings.minio_bucket:
        raise AppError(403, "IMAGE_BUCKET_FORBIDDEN", "禁止访问该桶")
    safe_path = _safe_object_path(object_path)
    if safe_path is None:
        raise AppError(400, "IMAGE_PATH_INVALID", "图片路径非法")
    ext = "." + safe_path.rsplit(".", 1)[-1].lower() if "." in safe_path else ""
    mime = _IMAGE_MIME.get(ext)
    if mime is None:
        raise AppError(415, "IMAGE_TYPE_UNSUPPORTED", "不支持的图片格式")

    client = _get_minio_client()
    if client is None:
        raise AppError(503, "IMAGE_BACKEND_UNAVAILABLE", "图片服务未配置")

    def _fetch() -> bytes:
        response = client.get_object(settings.minio_bucket, safe_path)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception:
        logger.warning("image proxy fetch failed: bucket=%s path=%s", bucket, safe_path, exc_info=True)
        raise AppError(502, "IMAGE_FETCH_FAILED", "图片读取失败")

    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
