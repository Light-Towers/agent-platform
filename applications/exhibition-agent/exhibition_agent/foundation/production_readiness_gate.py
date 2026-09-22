"""
F06 Production Readiness Gate — 门禁引擎 + Data Ready 门 + 审计

六门：Identity(F01) / Knowledge(F03) / Data(F04) / Evaluation(F05) / Security(F02) / Observability(§20)
门状态：NOT_READY / READY / PASS
聚合：6 门全 PASS → APPROVED；否则 NOT_APPROVED + 未过门清单

硬规则：
  🔴 SYNTHETIC 数据永远不能 Production Ready（INV-3）
  未 APPROVED 的 Agent 对外须标「演示/非生产」

迁移来源：mingyang-warehouse/ontology/web/backend/production_readiness_gate.py（2026-09-22）
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_MANIFEST_PATH = os.path.join(_BACKEND_DIR, "readiness_gate_manifest.json")
_METRIC_REGISTRY_PATH = os.path.join(_BACKEND_DIR, "metric_registry.json")
_AUDIT_LOG_PATH = os.path.join(_DATA_DIR, "readiness_gate_audit.json")
_SQLITE_DB_PATH = os.path.join(_DATA_DIR, "local_test.db")

GATE_NOT_READY = "NOT_READY"
GATE_READY = "READY"
GATE_PASS = "PASS"

APPROVED = "APPROVED"
NOT_APPROVED = "NOT_APPROVED"


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_manifest() -> dict:
    return _load_json(_MANIFEST_PATH)


def _load_registry() -> dict:
    return _load_json(_METRIC_REGISTRY_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_gate_status() -> dict:
    """
    返回六门状态 + 聚合结论。
    Data 门由 _evaluate_data_gate() 运行时推导；其余门读 manifest。
    """
    manifest = _load_manifest()
    gates = manifest["gates"]

    data_result = _evaluate_data_gate()
    gates["data"]["status"] = data_result["status"]
    gates["data"]["details"] = data_result["details"]

    failed_gates = []
    for gid, g in gates.items():
        if g["status"] != GATE_PASS:
            failed_gates.append({"gate_id": gid, "name": g["name"], "status": g["status"]})

    approved = len(failed_gates) == 0
    result = {
        "approved": approved,
        "conclusion": APPROVED if approved else NOT_APPROVED,
        "failed_gates": failed_gates,
        "gates": {gid: {"name": g["name"], "status": g["status"], "implemented": g.get("implemented", False)} for gid, g in gates.items()},
    }
    return result


def set_gate_manual(gate_id: str, status: str, evidence: str) -> dict:
    """
    供占位门手动设置状态（F01/F02/F03/F05/§20 后续接入用）。
    """
    manifest = _load_manifest()
    if gate_id not in manifest["gates"]:
        return {"error": f"gate '{gate_id}' not found"}

    valid_statuses = {GATE_NOT_READY, GATE_READY, GATE_PASS}
    if status not in valid_statuses:
        return {"error": f"status must be in {valid_statuses}"}

    manifest["gates"][gate_id]["status"] = status
    manifest["gates"][gate_id]["manual_evidence"] = evidence
    manifest["gates"][gate_id]["manual_set_at"] = _now_iso()
    _save_json(_MANIFEST_PATH, manifest)
    return {"gate_id": gate_id, "status": status, "evidence": evidence}


def _evaluate_data_gate() -> dict:
    """
    Data Ready 门：对 metric_registry 中每个 CONNECTED 指标执行 Data Ready 判定。

    判据：
    1. SYNTHETIC 指标 → NOT_READY（硬规则 INV-3，永不升 VERIFIED）
    2. BLOCKED 指标 → NOT_READY（受数据限制，不可算）
    3. CONNECTED 指标 → 执行 sql_template，返回行数>0 → READY → PASS
    4. VERIFIED 指标 → PASS（已通过）
    """
    registry = _load_registry()
    metrics = registry["metrics"]

    metric_results = []
    any_pass = True
    has_connectable = False

    for mid, m in metrics.items():
        status = m["status"]
        result = {"metric_id": mid, "name": m["name"], "status": status}

        if status == "VERIFIED":
            result["data_ready"] = True
            result["reason"] = "已 VERIFIED"
            metric_results.append(result)
            continue

        if status == "BLOCKED":
            result["data_ready"] = False
            result["reason"] = "BLOCKED: 受数据限制不可算"
            any_pass = False
            metric_results.append(result)
            continue

        if status == "SYNTHETIC":
            result["data_ready"] = False
            result["reason"] = "SYNTHETIC: 合成数据永不 Production Ready（INV-3）"
            any_pass = False
            metric_results.append(result)
            continue

        if status == "CONNECTED":
            has_connectable = True
            sql_template = m.get("sql_template")
            if not sql_template:
                result["data_ready"] = False
                result["reason"] = "CONNECTED 但无 sql_template"
                any_pass = False
                metric_results.append(result)
                continue

            exec_result = _execute_sql_template(sql_template)
            result["sql_executable"] = exec_result["executable"]
            result["row_count"] = exec_result.get("row_count")

            if exec_result["executable"] and exec_result["row_count"] > 0:
                result["data_ready"] = True
                result["reason"] = f"sql_template 执行成功，返回 {exec_result['row_count']} 行"
            else:
                result["data_ready"] = False
                result["reason"] = exec_result.get("error", f"sql_template 返回 0 行")
                any_pass = False
            metric_results.append(result)
            continue

        result["data_ready"] = False
        result["reason"] = f"未处理状态: {status}"
        any_pass = False
        metric_results.append(result)

    gate_status = GATE_PASS if (any_pass and has_connectable) else GATE_NOT_READY
    return {"status": gate_status, "details": metric_results}


def _execute_sql_template(sql: str) -> dict:
    """
    在 SQLite 真库执行 sql_template，返回执行结果。
    TODO: F02 接入后，由 F02 提供 READY 数据源连接。
    """
    if not os.path.exists(_SQLITE_DB_PATH):
        return {"executable": False, "error": f"SQLite DB not found: {_SQLITE_DB_PATH}"}

    try:
        conn = sqlite3.connect(_SQLITE_DB_PATH)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return {"executable": True, "row_count": len(rows)}
    except Exception as e:
        return {"executable": False, "error": str(e)}


def run_data_ready_gate_and_upgrade() -> dict:
    """
    执行 Data Ready 门，对通过的 CONNECTED 指标升 VERIFIED，写回 metric_registry.json。

    硬规则：SYNTHETIC 指标永不升 VERIFIED（INV-3）。

    返回：各指标判定结果 + 升降动作 + 审计记录。
    """
    registry = _load_registry()
    metrics = registry["metrics"]

    evaluation_results = []
    upgrades = []

    for mid, m in metrics.items():
        status = m["status"]
        result = {"metric_id": mid, "name": m["name"], "before_status": status}

        if status == "SYNTHETIC":
            result["action"] = "NONE"
            result["reason"] = "SYNTHETIC: 合成数据永不升 VERIFIED（INV-3 硬规则）"
            result["after_status"] = status
            evaluation_results.append(result)
            continue

        if status == "BLOCKED":
            result["action"] = "NONE"
            result["reason"] = "BLOCKED: 受数据限制，不可升 VERIFIED"
            result["after_status"] = status
            evaluation_results.append(result)
            continue

        if status == "VERIFIED":
            result["action"] = "NONE"
            result["reason"] = "已 VERIFIED，无需升级"
            result["after_status"] = status
            evaluation_results.append(result)
            continue

        if status == "CONNECTED":
            sql_template = m.get("sql_template")
            if not sql_template:
                result["action"] = "NONE"
                result["reason"] = "无 sql_template"
                result["after_status"] = status
                evaluation_results.append(result)
                continue

            exec_result = _execute_sql_template(sql_template)
            result["sql_executable"] = exec_result["executable"]
            result["row_count"] = exec_result.get("row_count")

            if exec_result["executable"] and exec_result["row_count"] > 0:
                m["status"] = "VERIFIED"
                m["status_reason"] = f"F06 Data Ready 门通过，{datetime.now().strftime('%Y-%m-%d')}（sql_template 返回 {exec_result['row_count']} 行）"
                result["action"] = "UPGRADE"
                result["reason"] = f"Data Ready PASS: sql 返回 {exec_result['row_count']} 行"
                result["after_status"] = "VERIFIED"
                upgrades.append(mid)
            else:
                result["action"] = "NONE"
                result["reason"] = f"Data Ready FAIL: {exec_result.get('error', '返回 0 行')}"
                result["after_status"] = status
            evaluation_results.append(result)
            continue

        result["action"] = "NONE"
        result["reason"] = f"未处理状态: {status}"
        result["after_status"] = status
        evaluation_results.append(result)

    _save_json(_METRIC_REGISTRY_PATH, registry)

    audit_record = _write_audit(evaluation_results, upgrades)

    return {
        "evaluation": evaluation_results,
        "upgrades": upgrades,
        "audit": audit_record,
    }


def _write_audit(evaluation_results: list, upgrades: list) -> dict:
    """
    审计留痕：每次判定记录时间、各门证据、结论、判定人。
    存独立 JSON 日志，不污染分析仓 168 表（F-2）。
    """
    audit_record = {
        "timestamp": _now_iso(),
        "judge": "mock_auto (F06 MVP, 待 D1 拍板双签)",
        "gate": "data_ready",
        "evaluation": evaluation_results,
        "upgrades": upgrades,
        "conclusion": f"{len(upgrades)} metric(s) upgraded to VERIFIED",
    }

    audit_log = []
    if os.path.exists(_AUDIT_LOG_PATH):
        try:
            audit_log = _load_json(_AUDIT_LOG_PATH)
            if not isinstance(audit_log, list):
                audit_log = []
        except Exception:
            audit_log = []

    audit_log.append(audit_record)
    _save_json(_AUDIT_LOG_PATH, audit_log)

    return audit_record


def get_audit_log() -> list:
    """读取审计日志。"""
    if not os.path.exists(_AUDIT_LOG_PATH):
        return []
    return _load_json(_AUDIT_LOG_PATH)


def is_production_ready(skill_id: str) -> dict:
    """
    判定某 skill 是否 Production Ready。

    硬规则：SYNTHETIC → 永不 Production Ready（INV-3）。
    """
    from . import metric_registry as mr

    readiness = mr.get_readiness(skill_id)
    gate_status = get_gate_status()

    if readiness == "SYNTHETIC":
        return {
            "skill_id": skill_id,
            "production_ready": False,
            "reason": "SYNTHETIC: 合成数据永不 Production Ready（INV-3）",
            "label": "演示/非生产",
        }

    if readiness == "N/A (write)":
        return {
            "skill_id": skill_id,
            "production_ready": False,
            "reason": "写操作，不适用 Production Ready 判定",
            "label": "N/A (write)",
        }

    if not gate_status["approved"]:
        failed = [g["gate_id"] for g in gate_status["failed_gates"]]
        return {
            "skill_id": skill_id,
            "production_ready": False,
            "reason": f"门禁未全通过，failed_gates: {failed}",
            "label": "演示/非生产",
            "readiness": readiness,
        }

    return {
        "skill_id": skill_id,
        "production_ready": True,
        "reason": "全门通过 + readiness=CONNECTED",
        "label": "Production Ready",
        "readiness": readiness,
    }


# === 六门 evidence 查询（件 13 Data Readiness 补全）===
# 每门调用对应 foundation 模块的状态函数，返回 NOT_READY/READY/PASS + reason + details。
# 六门全 PASS → APPROVED；否则 NOT_APPROVED + 未过门清单。


def _map_evidence_status(status: str) -> str:
    """把 foundation 模块返回的 status 映射到门状态 {NOT_READY, READY, PASS}。"""
    if status in (GATE_NOT_READY, GATE_READY, GATE_PASS):
        return status
    return GATE_NOT_READY


def _evaluate_identity_gate() -> dict:
    """
    Identity Ready 门：F01 ExecutionContext 状态。
    F01 已实现签名/校验/scope 过滤骨架，待 D1-D5 拍板 + 全链路落地。
    """
    return {
        "status": GATE_NOT_READY,
        "reason": "F01 已实现签名/校验/scope 过滤骨架，待 D1-D5 拍板 + 全链路落地",
        "details": {
            "signing": "已实现（HMAC-SHA256）",
            "scope_filter": "已实现（enforce_scope_filter）",
            "cross_tenant_audit": "已实现",
            "pending": "D1-D5 待业务方拍板",
        },
    }


def _evaluate_knowledge_gate() -> dict:
    """Knowledge Ready 门：调用 F03 knowledge_lifecycle.knowledge_readiness()。"""
    from . import knowledge_lifecycle as kl

    evidence = kl.knowledge_readiness()
    return {
        "status": _map_evidence_status(evidence.get("status", "")),
        "reason": evidence.get("reason", ""),
        "details": evidence.get("details", {}),
    }


def _evaluate_evaluation_gate() -> dict:
    """Evaluation Pass 门：调用 F05 evaluation.get_evaluation_readiness()。"""
    from . import evaluation as ev

    evidence = ev.get_evaluation_readiness()
    return {
        "status": _map_evidence_status(evidence.get("status", "")),
        "reason": evidence.get("reason", ""),
        "details": evidence.get("details", {}),
    }


def _evaluate_security_gate() -> dict:
    """Security Pass 门：调用 F02 data_egress.get_security_readiness()。"""
    from . import data_egress as de

    evidence = de.get_security_readiness()
    return {
        "status": _map_evidence_status(evidence.get("status", "")),
        "reason": evidence.get("reason", ""),
        "details": evidence.get("details", {}),
    }


def _evaluate_observability_gate() -> dict:
    """
    Observability Pass 门：observability/ 状态。
    C4 trace 已实现 11 字段，OTel/metrics/llm_obs 骨架就位，待全链路接入 + 基线标定。
    """
    return {
        "status": GATE_NOT_READY,
        "reason": "C4 trace 已实现 11 字段，OTel/metrics/llm_obs 骨架就位，待全链路接入 + 基线标定",
        "details": {
            "trace_fields": "C4 11 字段已实现",
            "otel": "骨架就位",
            "metrics": "骨架就位",
            "llm_obs": "骨架就位（NoOp/Langfuse/LangSmith）",
            "pending": "全链路接入 + 成本基线标定",
        },
    }


_GATE_EVALUATORS = {
    "identity": _evaluate_identity_gate,
    "knowledge": _evaluate_knowledge_gate,
    "data": _evaluate_data_gate,
    "evaluation": _evaluate_evaluation_gate,
    "security": _evaluate_security_gate,
    "observability": _evaluate_observability_gate,
}


def get_gate_status_with_evidence() -> dict:
    """
    返回六门状态 + evidence + 聚合结论（件 13 Data Readiness 补全）。

    每门调用对应 foundation 模块的状态函数：
      identity      → _evaluate_identity_gate（F01 占位）
      knowledge     → knowledge_lifecycle.knowledge_readiness()
      data          → _evaluate_data_gate（运行时执行 sql_template）
      evaluation    → evaluation.get_evaluation_readiness()
      security      → data_egress.get_security_readiness()
      observability → _evaluate_observability_gate（占位）

    每门返回 NOT_READY/READY/PASS，六门全 PASS → APPROVED。
    与 get_gate_status() 的区别：本函数不读写 manifest，纯运行时推导 evidence。
    """
    manifest = _load_manifest()
    gates_meta = manifest["gates"]

    evidence_results: dict = {}
    failed_gates: list = []

    for gid, evaluator in _GATE_EVALUATORS.items():
        ev_result = evaluator()
        gate_status = ev_result["status"]
        evidence_results[gid] = {
            "name": gates_meta[gid]["name"],
            "status": gate_status,
            "implemented": gates_meta[gid].get("implemented", False),
            "reason": ev_result.get("reason", ""),
            "details": ev_result.get("details", {}),
        }
        if gate_status != GATE_PASS:
            failed_gates.append({"gate_id": gid, "name": gates_meta[gid]["name"], "status": gate_status})

    approved = len(failed_gates) == 0
    return {
        "approved": approved,
        "conclusion": APPROVED if approved else NOT_APPROVED,
        "failed_gates": failed_gates,
        "gates": evidence_results,
    }
