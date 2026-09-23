"""
F03 Knowledge Supply Chain & Lifecycle — 脚手架版

状态机：DRAFT → REVIEWING → PUBLISHED → EXPIRED / REVOKED / SUPERSEDED
PUBLISHED 是唯一可进入生产检索的状态。

硬规则：
  缺 authority / effective_from / effective_to 不得 PUBLISHED
  非 PUBLISHED 知识不得出现在生产回答中
  无 Citation 的知识型答案 → 拒绝作答
  每次状态变更写审计

迁移来源：mingyang-warehouse/ontology/web/backend/knowledge_lifecycle.py（2026-09-22）
"""

import os
from datetime import datetime, timezone
from enum import Enum

from ._audit_writer import append_audit_record, read_audit_log

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_AUDIT_LOG_PATH = os.path.join(_DATA_DIR, "knowledge_lifecycle_audit.json")


class KNOWLEDGE_STATUS(str, Enum):
    DRAFT = "DRAFT"
    REVIEWING = "REVIEWING"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


_VALID_TRANSITIONS = {
    (KNOWLEDGE_STATUS.DRAFT, KNOWLEDGE_STATUS.REVIEWING),
    (KNOWLEDGE_STATUS.REVIEWING, KNOWLEDGE_STATUS.PUBLISHED),
    (KNOWLEDGE_STATUS.PUBLISHED, KNOWLEDGE_STATUS.EXPIRED),
    (KNOWLEDGE_STATUS.PUBLISHED, KNOWLEDGE_STATUS.REVOKED),
    (KNOWLEDGE_STATUS.PUBLISHED, KNOWLEDGE_STATUS.SUPERSEDED),
}

_REQUIRED_METADATA_FIELDS = [
    "knowledge_id",
    "tenant_id",
    "scope_type",
    "authority",
    "effective_from",
    "effective_to",
]

_VALID_SCOPE_TYPES = {"PUBLIC", "PRIVATE"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class LifecycleStateMachine:
    """知识生命周期状态机"""

    @staticmethod
    def can_transition(frm: str, to: str) -> bool:
        try:
            s_from = KNOWLEDGE_STATUS(frm)
            s_to = KNOWLEDGE_STATUS(to)
        except ValueError:
            return False
        return (s_from, s_to) in _VALID_TRANSITIONS

    @staticmethod
    def transition(record: dict, to: str, actor: str) -> dict:
        """
        校验合法性 + 写审计 + 返回更新后的 record。
        如果迁移非法，抛 ValueError。
        """
        frm = record.get("status", "UNKNOWN")
        if not LifecycleStateMachine.can_transition(frm, to):
            raise ValueError(f"非法迁移: {frm} → {to}")

        updated = dict(record)
        updated["status"] = to
        updated["updated_at"] = _now_iso()

        _write_audit_record(record.get("knowledge_id", "unknown"), frm, to, actor)

        return updated


def validate_metadata(meta: dict) -> tuple:
    """
    校验 Metadata 必备项。
    返回 (ok: bool, errors: list)。
    缺以下任一即失败（不得 PUBLISHED）：
      knowledge_id / tenant_id / scope_type(PUBLIC|PRIVATE) /
      exhibition_id 或 venue_id（至少一非空）/
      authority / effective_from / effective_to
    """
    errors = []

    for field in _REQUIRED_METADATA_FIELDS:
        val = meta.get(field)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            errors.append(f"缺必填字段: {field}")

    scope_type = meta.get("scope_type")
    if scope_type and scope_type not in _VALID_SCOPE_TYPES:
        errors.append(f"scope_type 取值非法: {scope_type}，应为 PUBLIC 或 PRIVATE")

    exhibition_id = meta.get("exhibition_id")
    venue_id = meta.get("venue_id")
    if not exhibition_id and not venue_id:
        errors.append("exhibition_id 和 venue_id 至少需一个非空（用于推导具体性）")

    return (len(errors) == 0, errors)


def filter_published_for_retrieval(items: list) -> list:
    """
    返回仅 status==PUBLISHED 且 validate_metadata 通过且 effective_from ≤ now ≤ effective_to 的条目。
    供未来检索层调用（MVP 不接入）。
    """
    now = _now_date_str()
    result = []

    for item in items:
        if item.get("status") != KNOWLEDGE_STATUS.PUBLISHED:
            continue

        ok, _ = validate_metadata(item)
        if not ok:
            continue

        effective_from = item.get("effective_from", "")
        effective_to = item.get("effective_to", "")

        if effective_from and now < effective_from:
            continue
        if effective_to and now > effective_to:
            continue

        result.append(item)

    return result


def requires_citation(item: dict) -> bool:
    """
    判定某条知识回答是否需要 citation。
    知识型回答（基于 PUBLISHED 知识）必须附带 citation。
    """
    status = item.get("status", "")
    return status == KNOWLEDGE_STATUS.PUBLISHED


def assert_citation_or_refuse(answer: str, citations: list) -> str:
    """
    知识型答案无 citation → 返回拒绝消息。
    有 citation → 返回原答案。
    """
    if not citations or len(citations) == 0:
        return "无法基于未发布/无出处知识作答"
    return answer


def knowledge_readiness() -> dict:
    """
    供 F06 knowledge 门占位查询。
    不要改 readiness_gate_manifest.json 的 implemented 字段。
    """
    return {
        "status": "NOT_READY",
        "reason": "语料未接入 + F01 未落地",
        "details": {
            "corpus": "未接入（F03 §1: 会展知识 ⛔ 未接入）",
            "f01_execution_context": "未落地（tenant_id/scopes 依赖 F01）",
            "pending_decisions": ["D1-D5 待业务方拍板"],
        },
    }


def _write_audit_record(knowledge_id: str, frm: str, to: str, actor: str):
    """
    审计留痕：每次状态变更写记录。
    存独立 JSON 日志，不污染分析仓。
    """
    record = {
        "timestamp": _now_iso(),
        "knowledge_id": knowledge_id,
        "from_status": frm,
        "to_status": to,
        "actor": actor,
    }

    append_audit_record(_AUDIT_LOG_PATH, record)


def get_audit_log() -> list:
    """读取审计日志。"""
    return read_audit_log(_AUDIT_LOG_PATH)
