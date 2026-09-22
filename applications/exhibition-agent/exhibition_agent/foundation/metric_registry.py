"""
F04 Metric Registry — 查询模块 + readiness 映射函数

F04 status 六态（指标执行资格）：CANDIDATE/REGISTERED/BLOCKED/CONNECTED/VERIFIED/DEPRECATED
v2.1 readiness 四态（Tool 数据源就绪度）：SYNTHETIC/CONNECTED/PARTIAL/NOT_CONNECTED

关系：readiness = f(Tool 依赖的 metrics 的 status)
  CONNECTED/VERIFIED → CONNECTED
  REGISTERED/CANDIDATE → NOT_CONNECTED
  BLOCKED → PARTIAL
  DEPRECATED → NOT_CONNECTED

SYNTHETIC：Tool 级声明覆盖，不由 metric status 推导。

迁移来源：mingyang-warehouse/ontology/web/backend/metric_registry.py（2026-09-22）
"""

import json
import os
from typing import Optional
from enum import Enum

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_METRIC_REGISTRY_PATH = os.path.join(_BACKEND_DIR, "metric_registry.json")
_TOOL_CATALOG_PATH = os.path.join(_BACKEND_DIR, "tool_catalog.json")


class MetricStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    REGISTERED = "REGISTERED"
    BLOCKED = "BLOCKED"
    CONNECTED = "CONNECTED"
    VERIFIED = "VERIFIED"
    DEPRECATED = "DEPRECATED"


class Readiness(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    CONNECTED = "CONNECTED"
    PARTIAL = "PARTIAL"
    NOT_CONNECTED = "NOT_CONNECTED"
    NA_WRITE = "N/A (write)"


_STATUS_TO_READINESS = {
    MetricStatus.CONNECTED: Readiness.CONNECTED,
    MetricStatus.VERIFIED: Readiness.CONNECTED,
    MetricStatus.REGISTERED: Readiness.NOT_CONNECTED,
    MetricStatus.CANDIDATE: Readiness.NOT_CONNECTED,
    MetricStatus.BLOCKED: Readiness.PARTIAL,
    MetricStatus.DEPRECATED: Readiness.NOT_CONNECTED,
}


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_registry() -> dict:
    return _load_json(_METRIC_REGISTRY_PATH)


def _load_catalog() -> dict:
    return _load_json(_TOOL_CATALOG_PATH)


def get_metric(metric_id: str) -> Optional[dict]:
    registry = _load_registry()
    return registry.get("metrics", {}).get(metric_id)


def get_metric_status(metric_id: str) -> Optional[str]:
    metric = get_metric(metric_id)
    if metric is None:
        return None
    return metric.get("status")


def get_all_metrics() -> dict:
    return _load_registry().get("metrics", {})


def _metric_status_to_readiness(status: str) -> Readiness:
    try:
        ms = MetricStatus(status)
    except ValueError:
        return Readiness.NOT_CONNECTED
    return _STATUS_TO_READINESS[ms]


def _aggregate_readiness(metric_readiness_list: list) -> Readiness:
    if not metric_readiness_list:
        return Readiness.NOT_CONNECTED

    has_partial = Readiness.PARTIAL in metric_readiness_list
    has_connected = Readiness.CONNECTED in metric_readiness_list
    has_not_connected = Readiness.NOT_CONNECTED in metric_readiness_list

    if has_partial:
        return Readiness.PARTIAL
    if has_not_connected and has_connected:
        return Readiness.PARTIAL
    if has_not_connected:
        return Readiness.NOT_CONNECTED
    return Readiness.CONNECTED


def get_readiness(skill_id: str) -> str:
    """
    推导 skill 的运行时 readiness 四态。

    优先级：
    1. Tool 级 SYNTHETIC 声明覆盖 → SYNTHETIC
    2. 写操作（N/A (write)）→ N/A (write)
    3. 由 depends_on_metrics 的 metric status 聚合推导
    4. 无 metric 依赖 → NOT_CONNECTED
    """
    catalog = _load_catalog()
    skill = catalog.get("skills", {}).get(skill_id)
    if skill is None:
        return Readiness.NOT_CONNECTED

    static_readiness = skill.get("readiness", "")

    if static_readiness == Readiness.SYNTHETIC:
        return Readiness.SYNTHETIC

    if static_readiness == Readiness.NA_WRITE:
        return Readiness.NA_WRITE

    depends_on_metrics = skill.get("depends_on_metrics", [])
    if not depends_on_metrics:
        return Readiness.NOT_CONNECTED

    metric_readiness_list = []
    for metric_id in depends_on_metrics:
        status = get_metric_status(metric_id)
        if status is None:
            metric_readiness_list.append(Readiness.NOT_CONNECTED)
        else:
            metric_readiness_list.append(_metric_status_to_readiness(status))

    return _aggregate_readiness(metric_readiness_list)


def get_readiness_with_reason(skill_id: str) -> dict:
    """
    返回 readiness + 推导原因（供调试/前端展示）。
    """
    catalog = _load_catalog()
    skill = catalog.get("skills", {}).get(skill_id)
    if skill is None:
        return {"readiness": Readiness.NOT_CONNECTED, "reason": f"skill '{skill_id}' not found in catalog"}

    static_readiness = skill.get("readiness", "")

    if static_readiness == Readiness.SYNTHETIC:
        return {
            "readiness": Readiness.SYNTHETIC,
            "reason": "Tool 级 SYNTHETIC 声明覆盖（全合成数据源）",
            "source": "tool_override",
        }

    if static_readiness == Readiness.NA_WRITE:
        return {
            "readiness": Readiness.NA_WRITE,
            "reason": "写操作，readiness 不适用",
            "source": "write_op",
        }

    depends_on_metrics = skill.get("depends_on_metrics", [])
    if not depends_on_metrics:
        return {
            "readiness": Readiness.NOT_CONNECTED,
            "reason": "无 metric 依赖声明",
            "source": "no_dependencies",
        }

    metric_details = []
    metric_readiness_list = []
    for metric_id in depends_on_metrics:
        metric = get_metric(metric_id)
        if metric is None:
            metric_readiness_list.append(Readiness.NOT_CONNECTED)
            metric_details.append({"metric_id": metric_id, "status": None, "readiness": Readiness.NOT_CONNECTED, "note": "metric not found"})
        else:
            status = metric.get("status")
            r = _metric_status_to_readiness(status)
            metric_readiness_list.append(r)
            metric_details.append({"metric_id": metric_id, "name": metric.get("name"), "status": status, "readiness": r})

    aggregated = _aggregate_readiness(metric_readiness_list)
    return {
        "readiness": aggregated,
        "reason": f"由 {len(depends_on_metrics)} 个 metric status 聚合推导",
        "source": "metric_registry",
        "metrics": metric_details,
    }
