"""
F02 Data Classification / Egress / Model Routing — 脚手架版

三层治理：
  1. 数据分级（DataClass）：PUBLIC / INTERNAL / CONFIDENTIAL / PII / FINANCIAL
  2. 出域策略（EgressPolicy）：企业 A 默认档 / 企业 B 全 Private
  3. 模型路由（route_model）：Small / Private / Cloud；出域未过 → deny（不降级）

硬规则：
  未分类数据按 CONFIDENTIAL 处理（默认从严）
  PII 入模前脱敏，不依赖模型自觉
  出域策略未通过 → 直接拒绝，不得降级到云模型
  每次调用 100% 审计

迁移来源：mingyang-warehouse/ontology/web/backend/data_egress.py（2026-09-22）
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_AUDIT_LOG_PATH = os.path.join(_DATA_DIR, "data_egress_audit.json")


class DataClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    PII = "PII"
    FINANCIAL = "FINANCIAL"


class EgressDecision(str, Enum):
    ALLOW = "allow"
    MASK_THEN_ALLOW = "mask_then_allow"
    DENY = "deny"


_FIELD_CLASSIFICATION = {
    "phone": DataClass.PII,
    "mobile": DataClass.PII,
    "email": DataClass.PII,
    "id_card": DataClass.PII,
    "identity": DataClass.PII,
    "contract_amount": DataClass.FINANCIAL,
    "revenue": DataClass.FINANCIAL,
    "income": DataClass.FINANCIAL,
    "cost": DataClass.FINANCIAL,
    "profit": DataClass.FINANCIAL,
    "price": DataClass.FINANCIAL,
    "contract": DataClass.CONFIDENTIAL,
    "quote": DataClass.CONFIDENTIAL,
    "report": DataClass.CONFIDENTIAL,
    "analysis": DataClass.CONFIDENTIAL,
    "strategy": DataClass.CONFIDENTIAL,
    "plan": DataClass.CONFIDENTIAL,
    "description": DataClass.PUBLIC,
    "title": DataClass.PUBLIC,
    "summary": DataClass.PUBLIC,
    "news": DataClass.PUBLIC,
    "policy": DataClass.PUBLIC,
    "spec": DataClass.PUBLIC,
    "manual": DataClass.INTERNAL,
    "doc": DataClass.INTERNAL,
    "document": DataClass.INTERNAL,
    "internal": DataClass.INTERNAL,
}


def classify(descriptor: str) -> DataClass:
    """
    按描述符（字段名/类型/标注）分级。
    未分类 → CONFIDENTIAL（默认从严）。
    """
    if not descriptor:
        return DataClass.CONFIDENTIAL

    key = descriptor.lower().strip()
    for field_name, dc in _FIELD_CLASSIFICATION.items():
        if field_name in key or key in field_name:
            return dc

    return DataClass.CONFIDENTIAL


class EgressPolicy:
    """出域策略（企业级 Policy，不写死在代码里）。"""

    POLICY_ENTERPRISE_A = "enterprise_a"
    POLICY_ENTERPRISE_B = "enterprise_b"

    def __init__(self, policy_name: str = "enterprise_a"):
        self.policy_name = policy_name
        if policy_name == self.POLICY_ENTERPRISE_A:
            self._rules = {
                DataClass.PUBLIC: EgressDecision.ALLOW,
                DataClass.INTERNAL: EgressDecision.MASK_THEN_ALLOW,
                DataClass.CONFIDENTIAL: EgressDecision.DENY,
                DataClass.PII: EgressDecision.DENY,
                DataClass.FINANCIAL: EgressDecision.DENY,
            }
        elif policy_name == self.POLICY_ENTERPRISE_B:
            self._rules = {dc: EgressDecision.DENY for dc in DataClass}
        else:
            self._rules = {dc: EgressDecision.DENY for dc in DataClass}

    def get_decision(self, data_class: DataClass) -> EgressDecision:
        return self._rules.get(data_class, EgressDecision.DENY)

    def allows_cloud(self, data_class: DataClass) -> bool:
        dec = self.get_decision(data_class)
        return dec in (EgressDecision.ALLOW, EgressDecision.MASK_THEN_ALLOW)


def evaluate_egress(data_class: DataClass, policy: EgressPolicy) -> dict:
    """
    评估出域决策。
    返回 allow / mask_then_allow / deny + 建议模型类别。
    """
    decision = policy.get_decision(data_class)

    if decision == EgressDecision.ALLOW:
        return {"decision": "allow", "model_category": "Cloud", "requires_masking": False}
    elif decision == EgressDecision.MASK_THEN_ALLOW:
        return {"decision": "mask_then_allow", "model_category": "Cloud", "requires_masking": True}
    else:
        return {"decision": "deny", "model_category": "Private", "requires_masking": False}


_PATTERNS = {
    "phone": re.compile(r'1[3-9]\d{2}[-\s]?\d{4}[-\s]?\d{3}'),
    "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
    "id_card": re.compile(r'[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]'),
}


def mask_pii(text: str) -> str:
    """
    规则脱敏（手机号/邮箱/身份证掩码），入模前调用。
    手机号 → 138****1234
    邮箱 → z***@example.com
    身份证 → 110***********1234
    """
    if not text:
        return text

    result = text

    result = _PATTERNS["phone"].sub(
        lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:],
        result
    )

    result = _PATTERNS["email"].sub(
        lambda m: m.group(0)[0] + "***@" + m.group(0).split("@")[1],
        result
    )

    result = _PATTERNS["id_card"].sub(
        lambda m: m.group(0)[:3] + "***********" + m.group(0)[-4:],
        result
    )

    return result


def route_model(data_class: DataClass, policy: EgressPolicy, task_type: str = "general") -> dict:
    """
    模型路由：Small / Private / Cloud。
    出域未过 → deny（不降级到云模型）。
    Agent 不得自选模型，route_model 是唯一出口。
    """
    egress = evaluate_egress(data_class, policy)

    if egress["decision"] == "deny":
        return {
            "model_category": "deny",
            "reason": f"出域策略未通过（{data_class} → {policy.policy_name}）",
            "action": "REJECT",
        }

    if task_type in ("routing", "intent_classification", "query_rewrite", "guardrail"):
        return {
            "model_category": "Small",
            "reason": "轻量前置任务 → Small LLM",
            "action": egress["decision"],
        }

    if egress["model_category"] == "Cloud":
        return {
            "model_category": "Cloud",
            "reason": f"{data_class} 允许出域 → Cloud LLM",
            "action": egress["decision"],
            "requires_masking": egress["requires_masking"],
        }

    return {
        "model_category": "Private",
        "reason": f"{data_class} → Private LLM",
        "action": egress["decision"],
    }


def record_egress_audit(
    data_class: DataClass,
    decision: str,
    model_category: str,
    request_id: Optional[str] = None,
    task_type: str = "general",
    masked: bool = False,
) -> dict:
    """
    每次调用 100% 审计。
    写独立 JSON 日志，不污染分析仓。
    不记录 PII 原文（RD7）。
    """
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_class": str(data_class),
        "decision": decision,
        "model_category": model_category,
        "task_type": task_type,
        "masked": masked,
        "request_id": request_id or str(uuid.uuid4()),
    }

    audit_log = []
    if os.path.exists(_AUDIT_LOG_PATH):
        try:
            with open(_AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                audit_log = json.load(f)
            if not isinstance(audit_log, list):
                audit_log = []
        except Exception:  # noqa: BLE001
            audit_log = []

    audit_log.append(record)

    os.makedirs(os.path.dirname(_AUDIT_LOG_PATH), exist_ok=True)
    with open(_AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(audit_log, f, ensure_ascii=False, indent=2)

    return record


def get_audit_log() -> list:
    """读取审计日志。"""
    if not os.path.exists(_AUDIT_LOG_PATH):
        return []
    with open(_AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def execute_llm(model_category: str, prompt: str, **kwargs) -> dict:
    """
    LLM 调用实体：按 model_category 分发到 Small / Private / Cloud。

    route_model 返回 model_category 后，由调用方按 category 调用本函数。
    当前为占位实现（TODO 待 F2 决策后接入真实 LLM 连接）：
      - Small：轻量前置任务（routing/intent_classification/query_rewrite/guardrail）
      - Private：敏感数据 / 出域未过 → 私有部署 Qwen / DeepSeek
      - Cloud：允许出域 → 云 LLM
      - deny：route_model 已拒绝，本函数不应被调用（返回 ROUTE_REJECTED）

    返回 dict 而非字符串，便于审计记录 model_category / latency / cost。
    不在此处记录 PII 原文（RD7）——调用方应在传入 prompt 前调用 mask_pii。
    """
    if model_category == "deny":
        return {
            "ok": False,
            "error": "ROUTE_REJECTED",
            "reason": "route_model 已拒绝，不应调用 execute_llm",
            "model_category": model_category,
        }

    # TODO(F2): 接入真实 LLM 连接
    # - Small：本地小模型（Qwen-0.5B / Phi-3-mini）或同进程规则
    # - Private：私有部署 Qwen / DeepSeek（HTTP 调用私有 endpoint）
    # - Cloud：云 LLM（OpenAI / Claude / 通义千问公共云）
    return {
        "ok": True,
        "model_category": model_category,
        "response": f"[占位 LLM/{model_category}] 真实连接待 F2 决策后接入",
        "prompt_len": len(prompt),
        "kwargs": kwargs,
    }


def get_security_readiness() -> dict:
    """
    供 F06 security 门占位查询。
    不要改 readiness_gate_manifest.json 的 implemented 字段。
    """
    return {
        "status": "NOT_READY",
        "reason": "出域策略待 D1 拍板 + LLM 层未接入",
        "details": {
            "D1_egress_policy": "默认企业 A",
            "D2_gpu_scale": "占位",
            "D3_deepseek": "第二阶段引入",
            "D4_field_classification": "规则分类器",
            "D5_cloud_vendors": "无（Private Only 优先）",
            "D6_small_llm": "占位",
            "D7_cost_limit": "不设置",
        },
    }
