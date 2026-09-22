"""
P1 Skill Router — discriminator→Tool 映射 + INV-4 整体拒绝 + F06 SYNTHETIC 拦截

route(skill_name, ctx, **discriminator) -> dict

门禁链：
  1. discriminator 映射到具体 Tool
  2. INV-4 scope 校验（enforce_scope_filter）— scope 不符 → 整体拒绝，不返回部分结果
  3. F06 readiness 门禁 — 生产模式 SYNTHETIC → 拒绝
  4. 返回 {tool, allowed, readiness_tag, endpoint}

集成（TODO 占位）：
  F02 data_egress.route_model/mask_pii — 出域/PII 占位
  F03 knowledge_lifecycle.filter_published_for_retrieval — 知识检索类 Skill 占位

迁移来源：mingyang-warehouse/ontology/web/backend/skill_router.py（2026-09-22）
"""

import json
import os
from typing import Optional

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_CATALOG_PATH = os.path.join(_BACKEND_DIR, "tool_catalog.json")

_DISCRIMINATOR_MAP = {
    "search_entity": {
        "entity_type": {
            "exhibition": "list_exhibitions",
            "exhibitor": "list_exhibitors",
            "audience": "search_portrait_audiences",
            "venue": "list_venues",
        }
    },
    "get_entity_profile": {
        "entity_type": {
            "exhibition": "portrait_exhibition",
            "exhibitor": "portrait_exhibitor",
            "audience": "portrait_audience",
            "venue": "venue_dimension",
        }
    },
    "list_business_records": {
        "record_type": {
            "contract": "contract",
            "safety": "safety",
            "safety_monthly": "safety_monthly",
            "meeting": "meeting",
            "clue": "clue",
        }
    },
    "recommend_exhibition": {
        "mode": {
            "profile_match": "exhibitor_exhibition_recommend",
            "schedule": "exhibitor_exhibition_schedule",
            "collaborative": "exhibition_cf_recommend",
        }
    },
    "get_venue_operation": {
        "card": {
            "radiation": "venue_audience_radiation",
            "positioning": "venue_positioning",
            "schedule": "venue_schedule",
            "project_fit": "venue_cf_recommend",
            "whitepaper": "venue_whitepaper",
        }
    },
    "get_strategy_insight": {
        "card": {
            "venue_recruit": "venue_recruit_strategy",
            "organizer_risk": "organizer_risk_signal",
            "organizer_retention": "organizer_retention",
            "venue_retention": "venue_retention_risk",
        }
    },
    "get_forecast": {
        "subject": {
            "exhibition": "exhibition_forecast",
            "venue": "venue_forecast",
            "audience_timeslot": "timeslot_predictions",
            "heat": "exhibition_heat",
        }
    },
}

_SCOPE_KEY_MAP = {
    "search_entity": None,
    "get_entity_profile": None,
    "get_overview": None,
    "list_business_records": None,
    "recommend_organizer": "venue_id",
    "recommend_venue": "sponsor_id",
    "recommend_exhibition": "exhibitor_id",
    "get_external_affinity": None,
    "get_venue_operation": "venue_id",
    "get_strategy_insight": "venue_id",
    "get_forecast": None,
    "create_lead": "sponsor_id",
    "delete_lead": "lead_id",
}


def _load_catalog() -> dict:
    with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_production_mode() -> bool:
    return os.environ.get("AGENT_MODE", "DEMO").upper() == "PRODUCTION"


def _resolve_tool_name(skill_name: str, catalog: dict, **discriminator) -> str:
    skill_def = catalog["skills"].get(skill_name)
    if not skill_def:
        raise ValueError(f"未知 Skill: {skill_name}")

    tools_list = skill_def["tools"]
    if len(tools_list) == 1:
        return tools_list[0]

    disc_map = _DISCRIMINATOR_MAP.get(skill_name)
    if not disc_map:
        if "tool_name" in discriminator:
            return discriminator["tool_name"]
        return tools_list[0]

    for disc_key, mapping in disc_map.items():
        disc_val = discriminator.get(disc_key)
        if disc_val and disc_val in mapping:
            return mapping[disc_val]

    return tools_list[0]


def _check_scope(ctx, skill_name: str, tool_name: str, catalog: dict, **discriminator) -> dict:
    scope_key = _SCOPE_KEY_MAP.get(skill_name)
    if not scope_key or not ctx:
        return {"allowed": True}

    target_id = discriminator.get(scope_key)
    if not target_id:
        return {"allowed": True}

    ctx_scope_ids = set()
    for s in getattr(ctx, "scopes", []):
        if ":" in s:
            _, sid = s.split(":", 1)
            ctx_scope_ids.add(sid)
        else:
            ctx_scope_ids.add(s)

    if ctx_scope_ids and target_id not in ctx_scope_ids:
        return {
            "allowed": False,
            "reason": f"scope 不符：目标 {scope_key}={target_id} 不在调用方 scope 内",
            "partial": False,
        }

    return {"allowed": True}


def route(skill_name: str, ctx=None, **discriminator) -> dict:
    """
    Skill→Tool 运行时路由。

    返回:
      {tool, allowed, readiness_tag, endpoint}  — 放行
      {allowed: false, reason, partial: false}  — INV-4 整体拒绝
      {allowed: false, reason, readiness_tag}   — F06 SYNTHETIC 拦截
    """
    catalog = _load_catalog()

    if skill_name not in catalog["skills"]:
        return {"allowed": False, "reason": f"未知 Skill: {skill_name}", "partial": False}

    tool_name = _resolve_tool_name(skill_name, catalog, **discriminator)

    if tool_name not in catalog["tools"]:
        return {"allowed": False, "reason": f"Tool {tool_name} 不在 catalog", "partial": False}

    tool_def = catalog["tools"][tool_name]

    scope_result = _check_scope(ctx, skill_name, tool_name, catalog, **discriminator)
    if not scope_result["allowed"]:
        return scope_result

    readiness_tag = tool_def.get("readiness", "UNKNOWN")

    if _is_production_mode() and readiness_tag == "SYNTHETIC":
        return {
            "allowed": False,
            "reason": "SYNTHETIC 禁入生产（INV-3）",
            "readiness_tag": "SYNTHETIC",
        }

    return {
        "tool": tool_name,
        "allowed": True,
        "readiness_tag": readiness_tag,
        "endpoint": tool_def["endpoint"],
    }


def get_all_skills() -> dict:
    catalog = _load_catalog()
    return catalog["skills"]


def get_all_tools() -> dict:
    catalog = _load_catalog()
    return catalog["tools"]
