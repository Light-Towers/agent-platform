"""
知识生命周期集成桥接（08+16 通用化）。

复用 shared_schemas.knowledge_lifecycle 状态契约，
为 knowledge-service 入库链路提供：
  - 入库前校验：metadata 必备项 + status 校验
  - 非 PUBLISHED 跳过生产入库（仅写审计）
  - PUBLISHED 前置校验：缺 authority/effective_from/effective_to 不得发布

P1-3 修复：依赖从 exhibition_agent 下沉到 shared_schemas，消除跨应用横向 import。
"""

from __future__ import annotations

from typing import Optional

from shared_schemas.knowledge_lifecycle import (
    KNOWLEDGE_STATUS,
    VALID_TRANSITIONS,
    validate_metadata,
)

from knowledge_service.core.logger import logger


def build_lifecycle_metadata(state: dict) -> dict:
    """
    从导入图 state 提取生命周期 metadata 字段，构造校验用 dict。
    """
    return {
        "knowledge_id": state.get("knowledge_id", ""),
        "tenant_id": state.get("tenant_id", ""),
        "scope_type": state.get("scope_type", ""),
        "authority": state.get("authority", ""),
        "effective_from": state.get("effective_from", ""),
        "effective_to": state.get("effective_to", ""),
        "exhibition_id": state.get("exhibition_id", ""),
        "venue_id": state.get("venue_id", ""),
    }


def should_publish_to_production(state: dict) -> tuple[bool, str]:
    """
    判定本次导入是否应进入生产检索入库（仅 PUBLISHED 且 metadata 校验通过）。

    :return: (should_publish, reason)
      - (True, "PUBLISHED")：进入生产入库
      - (False, reason)：跳过生产入库，reason 说明原因
    """
    status = state.get("status", "DRAFT")

    # 非 PUBLISHED 直接跳过（DRAFT/REVIEWING/EXPIRED/REVOKED/SUPERSEDED 均不入生产检索）
    if status != KNOWLEDGE_STATUS.PUBLISHED:
        logger.info(f"[lifecycle] status={status} 非 PUBLISHED，跳过生产入库（仅审计留痕）")
        return (False, f"status={status} 非 PUBLISHED")

    # PUBLISHED 需校验 metadata 必备项
    meta = build_lifecycle_metadata(state)
    ok, errors = validate_metadata(meta)
    if not ok:
        logger.warning(f"[lifecycle] PUBLISHED 但 metadata 校验失败：{errors}，降级跳过生产入库")
        return (False, f"metadata 校验失败: {errors}")

    return (True, "PUBLISHED")


def transition_status(state: dict, to: str, actor: str = "system") -> dict:
    """
    触发状态迁移（校验合法性 + 返回更新后 state）。
    非法迁移抛 ValueError。

    审计留痕由上层业务实现（本函数仅做契约校验）。
    """
    frm = state.get("status", "UNKNOWN")
    try:
        s_from = KNOWLEDGE_STATUS(frm)
        s_to = KNOWLEDGE_STATUS(to)
    except ValueError:
        raise ValueError(f"未知状态: {frm} 或 {to}") from None
    if (s_from, s_to) not in VALID_TRANSITIONS:
        raise ValueError(f"非法迁移: {frm} → {to}")
    state["status"] = to
    return state


def is_published(state: dict) -> bool:
    """便捷判定：state.status 是否为 PUBLISHED。"""
    return state.get("status", "DRAFT") == KNOWLEDGE_STATUS.PUBLISHED


def extract_tenant_scope_for_chunk(state: dict) -> tuple[Optional[str], Optional[str]]:
    """
    从 state 提取 (tenant_id, scope_type)，供入库时写入每条 chunk 的元数据字段。
    空值返回 None（Milvus 动态字段允许 None）。
    """
    tenant_id = state.get("tenant_id") or None
    scope_type = state.get("scope_type") or None
    return (tenant_id, scope_type)
