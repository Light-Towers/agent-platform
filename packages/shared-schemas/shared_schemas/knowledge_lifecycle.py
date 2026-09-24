"""知识生命周期状态契约（P1-3 下沉，原属 exhibition-agent）。

定义跨服务共享的：
- KNOWLEDGE_STATUS 枚举（6 状态）
- 合法转换表
- validate_metadata 校验函数

写审计等 I/O 操作保留在各应用本地（exhibition-agent 的 LifecycleStateMachine 继承此契约）。
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "KNOWLEDGE_STATUS",
    "VALID_TRANSITIONS",
    "REQUIRED_METADATA_FIELDS",
    "VALID_SCOPE_TYPES",
    "validate_metadata",
]


class KNOWLEDGE_STATUS(str, Enum):
    DRAFT = "DRAFT"
    REVIEWING = "REVIEWING"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


VALID_TRANSITIONS: set[tuple[KNOWLEDGE_STATUS, KNOWLEDGE_STATUS]] = {
    (KNOWLEDGE_STATUS.DRAFT, KNOWLEDGE_STATUS.REVIEWING),
    (KNOWLEDGE_STATUS.REVIEWING, KNOWLEDGE_STATUS.PUBLISHED),
    (KNOWLEDGE_STATUS.PUBLISHED, KNOWLEDGE_STATUS.EXPIRED),
    (KNOWLEDGE_STATUS.PUBLISHED, KNOWLEDGE_STATUS.REVOKED),
    (KNOWLEDGE_STATUS.PUBLISHED, KNOWLEDGE_STATUS.SUPERSEDED),
}

REQUIRED_METADATA_FIELDS: list[str] = [
    "knowledge_id",
    "tenant_id",
    "scope_type",
    "authority",
    "effective_from",
    "effective_to",
]

VALID_SCOPE_TYPES: set[str] = {"PUBLIC", "PRIVATE"}


def validate_metadata(meta: dict) -> tuple[bool, list[str]]:
    """
    校验 Metadata 必备项。
    返回 (ok: bool, errors: list)。
    缺以下任一即失败（不得 PUBLISHED）：
      knowledge_id / tenant_id / scope_type(PUBLIC|PRIVATE) /
      exhibition_id 或 venue_id（至少一非空）/
      authority / effective_from / effective_to
    """
    errors: list[str] = []

    for field in REQUIRED_METADATA_FIELDS:
        val = meta.get(field)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            errors.append(f"缺必填字段: {field}")

    scope_type = meta.get("scope_type")
    if scope_type and scope_type not in VALID_SCOPE_TYPES:
        errors.append(f"scope_type 取值非法: {scope_type}，应为 PUBLIC 或 PRIVATE")

    exhibition_id = meta.get("exhibition_id")
    venue_id = meta.get("venue_id")
    if not exhibition_id and not venue_id:
        errors.append("exhibition_id 和 venue_id 至少需一个非空（用于推导具体性）")

    return (len(errors) == 0, errors)
