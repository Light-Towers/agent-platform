# -*- coding: utf-8 -*-
"""会话上传图片的存储层（PG bytea，plan-image-qa-fullstack §刀3）。

agent_server 三副本无共享本地盘 ⇒ 图片存共享 PG（chat_images 表，migration 022）。
ref 不透明（不含集群内 host），读取时服务端断言 tenant 与 ref 前缀一致（租户隔离）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from agent_runtime.db import get_pool

from agent_server.config import get_settings

_ALLOWED_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def make_ref(tenant_id: str, session_id: str, ext: str) -> str:
    """不透明引用，首段是租户（读取时校验），不含 host/端口。"""
    return f"chat-images/{tenant_id}/{session_id}/{uuid.uuid4().hex}.{ext}"


def ext_for_content_type(content_type: str) -> str | None:
    return _ALLOWED_TYPES.get(content_type.split(";")[0].strip().lower())


async def save_image(ref: str, tenant_id: str, session_id: str, content: bytes, content_type: str) -> None:
    pool = get_pool()
    if pool is None:
        raise RuntimeError("chat_images: 数据库未配置")
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO chat_images (ref, tenant_id, session_id, content, content_type, byte_size) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            ref, tenant_id, session_id, content, content_type, len(content),
        )


async def get_image(ref: str, tenant_id: str) -> tuple[bytes, str] | None:
    """按 ref 取图；tenant 不匹配返回 None（防跨租户读）。"""
    if not ref.startswith(f"chat-images/{tenant_id}/"):
        return None
    pool = get_pool()
    if pool is None:
        return None
    async with pool.connection() as conn:
        row = await conn.fetchrow(
            "SELECT content, content_type FROM chat_images WHERE ref=$1 AND tenant_id=$2",
            ref, tenant_id,
        )
    if row is None:
        return None
    return bytes(row["content"]), row["content_type"]


async def delete_expired() -> int:
    """清理超过 TTL 的图片，返回删除条数（可由 lifespan 定时任务调用）。"""
    pool = get_pool()
    if pool is None:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().chat_image_ttl_days)
    async with pool.connection() as conn:
        return await conn.fetchval("DELETE FROM chat_images WHERE created_at < $1", cutoff)
