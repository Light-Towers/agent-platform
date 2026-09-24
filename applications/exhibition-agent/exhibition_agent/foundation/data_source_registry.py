"""
数据源/知识源台账 — F06 Data Readiness 补全（件 13）。

三类数据源：
  domain_api — warehouse REST 端点（exhibition/venue/exhibitor/audience/contract/safety/meeting/clue）
  knowledge  — knowledge-service（语料源，当前 NOT_CONNECTED）
  metric     — metric_registry.json 中的指标（readiness 从指标 status 推导）

每个数据源字段：source_id, name, type, readiness_level, last_checked

缺源降级（INV-10）：NOT_CONNECTED → 答"该指标待接入"，全程不生成 SQL。
SYNTHETIC 指标永不 Production Ready（INV-3）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_METRIC_REGISTRY_PATH = os.path.join(_BACKEND_DIR, "metric_registry.json")


class SourceType(str, Enum):
    DOMAIN_API = "domain_api"
    KNOWLEDGE = "knowledge"
    METRIC = "metric"


class ReadinessLevel(str, Enum):
    READY = "READY"
    CONNECTED = "CONNECTED"
    PARTIAL = "PARTIAL"
    SYNTHETIC = "SYNTHETIC"
    NOT_CONNECTED = "NOT_CONNECTED"


# Domain API 源：warehouse REST 端点（v1.2 直接 REST，已迁移接入）
_DOMAIN_API_SOURCES = [
    {"source_id": "api_exhibition", "name": "展会列表", "endpoint": "/api/exhibition", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_venue", "name": "场馆列表", "endpoint": "/api/venue", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_exhibitor", "name": "展商列表", "endpoint": "/api/exhibitor", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_audience", "name": "观众画像", "endpoint": "/api/portrait/audiences", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_contract", "name": "合同记录", "endpoint": "/api/contract", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_safety", "name": "安全记录", "endpoint": "/api/safety", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_meeting", "name": "会议记录", "endpoint": "/api/meeting", "readiness_level": ReadinessLevel.CONNECTED},
    {"source_id": "api_clue", "name": "线索记录", "endpoint": "/api/clue", "readiness_level": ReadinessLevel.CONNECTED},
]

# Knowledge 源：knowledge-service（语料未接入，F03 §1）
_KNOWLEDGE_SOURCES = [
    {
        "source_id": "knowledge_service",
        "name": "knowledge-service 语料",
        "readiness_level": ReadinessLevel.NOT_CONNECTED,
        "reason": "语料未接入（F03 §1: 会展知识 ⛔ 未接入）",
    },
]


PENDING_ANSWER = "该指标待接入"
"""INV-10 确定性回答，与 contract/error_codes.PENDING_ANSWER 一致。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_metric_sources() -> list:
    """从 metric_registry.json 推导 metric 源（readiness 从指标 readiness 字段读取）。"""
    registry = _load_json(_METRIC_REGISTRY_PATH)
    sources = []
    for mid, m in registry.get("metrics", {}).items():
        readiness = m.get("readiness", ReadinessLevel.NOT_CONNECTED)
        sources.append({
            "source_id": f"metric_{mid}",
            "name": m.get("name", mid),
            "metric_id": mid,
            "readiness_level": readiness,
            "status": m.get("status"),
        })
    return sources


def list_sources(source_type: Optional[str] = None) -> list:
    """列出所有数据源，可按类型过滤。"""
    sources = []
    for s in _DOMAIN_API_SOURCES:
        sources.append({**s, "type": SourceType.DOMAIN_API, "last_checked": _now_iso()})
    for s in _KNOWLEDGE_SOURCES:
        sources.append({**s, "type": SourceType.KNOWLEDGE, "last_checked": _now_iso()})
    for s in _build_metric_sources():
        sources.append({**s, "type": SourceType.METRIC, "last_checked": _now_iso()})

    if source_type is not None:
        sources = [s for s in sources if s["type"] == source_type or s["type"].value == source_type]
    return sources


def get_source(source_id: str) -> Optional[dict]:
    """按 source_id 查单个数据源。"""
    for s in list_sources():
        if s["source_id"] == source_id:
            return s
    return None


def get_readiness_level(source_id: str) -> Optional[str]:
    """查数据源的 readiness_level。"""
    s = get_source(source_id)
    if s is None:
        return None
    level = s["readiness_level"]
    return level.value if isinstance(level, ReadinessLevel) else level


def is_pending(source_id: str) -> bool:
    """是否命中缺源降级（NOT_CONNECTED → 答'待接入'）。"""
    level = get_readiness_level(source_id)
    return level == ReadinessLevel.NOT_CONNECTED


def pending_answer(source_id: str) -> dict:
    """
    缺源降级（INV-10）：NOT_CONNECTED → 答'该指标待接入'，全程不生成 SQL。
    非 NOT_CONNECTED → degraded=False（不应降级）。
    """
    if not is_pending(source_id):
        return {"degraded": False, "answer": None, "sql_generated": False}

    return {
        "degraded": True,
        "answer": PENDING_ANSWER,
        "sql_generated": False,  # INV-10：全程不生成 SQL
        "reason": f"数据源 {source_id} NOT_CONNECTED，降级答'待接入'",
    }


def get_registry_summary() -> dict:
    """台账汇总：各类型源数 + 各 readiness_level 计数。"""
    sources = list_sources()
    by_type: dict = {}
    by_readiness: dict = {}
    for s in sources:
        t = s["type"].value if isinstance(s["type"], SourceType) else s["type"]
        by_type[t] = by_type.get(t, 0) + 1
        r = s["readiness_level"]
        r = r.value if isinstance(r, ReadinessLevel) else r
        by_readiness[r] = by_readiness.get(r, 0) + 1
    return {
        "total": len(sources),
        "by_type": by_type,
        "by_readiness": by_readiness,
    }
