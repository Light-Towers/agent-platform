"""
F01 Identity / Tenant / ExecutionContext — MVP 切片（F1-C + R2/R3/R4/R5 + RD5/RD6 占位）

ExecutionContext 是 INV-8（隔离不靠 prompt）、INV-4（权限先行）、§18.4（ACL 前置过滤）的载体。

规则：
  R2: 缺失/签名无效 → 拒绝且不返回部分结果（防侧信道）
  R3: 跨租户访问尝试 100% 审计
  R4: Scope 过滤作为检索入参下推，非召回后过滤
  R5: DEMO 模式须标注"演示环境，非生产"
  RD5: inject_scope_params 必须平台注入，拒绝调用方自传
  RD7: 凭证/密钥不入代码、不入日志

迁移来源：mingyang-warehouse/ontology/web/backend/execution_context.py（2026-09-22）
"""

import base64
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ._audit_writer import append_audit_record, read_audit_log

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_AUDIT_LOG_PATH = os.path.join(_DATA_DIR, "execution_context_audit.json")

VALID_TENANT_TYPES = {"SPONSOR", "VENUE", "CONTRACTOR", "EXHIBITOR", "VENUE_OPERATOR"}
VALID_AUTH_SOURCES = {"IAM", "SSO", "PLATFORM_LOCAL"}


class Unauthorized(Exception):
    """R2: 上下文缺失或签名无效 → 拒绝。"""
    pass


class ForbiddenScopeInjection(Exception):
    """RD5: 调用方自传 inject_scope_params → 拒绝。"""
    pass


@dataclass
class ExecutionContext:
    user_id: str
    tenant_id: str
    tenant_type: str = "SPONSOR"
    roles: list = field(default_factory=list)
    scopes: list = field(default_factory=list)
    auth_source: str = "PLATFORM_LOCAL"
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        if not self.user_id:
            raise ValueError("user_id 必填")
        if not self.tenant_id:
            raise ValueError("tenant_id 必填")
        if self.tenant_type not in VALID_TENANT_TYPES:
            raise ValueError(f"tenant_type 必须是 {VALID_TENANT_TYPES}")
        if self.auth_source not in VALID_AUTH_SOURCES:
            raise ValueError(f"auth_source 必须是 {VALID_AUTH_SOURCES}")


def _get_signing_secret() -> str:
    """从环境变量读取签名密钥。缺失则报错，绝不硬编码兜底值。"""
    secret = os.environ.get("F01_SIGNING_SECRET")
    if not secret:
        raise RuntimeError(
            "F01_SIGNING_SECRET 环境变量未设置。"
            "请设置后启动（如: export F01_SIGNING_SECRET=your-secret）。"
            "绝不硬编码兜底值（RD7）。"
        )
    return secret


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("ascii"))


def sign_context(ctx: ExecutionContext, secret: Optional[str] = None) -> str:
    """
    HMAC 占位签名：token = b64(json(ctx)) + "." + b64(hmac_sha256(payload, secret))
    secret 缺失则从 F01_SIGNING_SECRET 环境变量读取。
    """
    if secret is None:
        secret = _get_signing_secret()

    payload = json.dumps(asdict(ctx), sort_keys=True, ensure_ascii=False).encode("utf-8")
    payload_b64 = _b64encode(payload)

    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64encode(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_context(token: str, secret: Optional[str] = None) -> Optional[ExecutionContext]:
    """
    验签：成功 → 返回 ExecutionContext；失败/无效 → 返回 None（R2）。
    """
    if secret is None:
        secret = _get_signing_secret()

    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None

        payload_b64, sig_b64 = parts

        expected_sig = hmac.new(
            secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
        ).digest()
        expected_sig_b64 = _b64encode(expected_sig)

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None

        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        return ExecutionContext(
            user_id=payload["user_id"],
            tenant_id=payload["tenant_id"],
            tenant_type=payload.get("tenant_type", "SPONSOR"),
            roles=payload.get("roles", []),
            scopes=payload.get("scopes", []),
            auth_source=payload.get("auth_source", "PLATFORM_LOCAL"),
            request_id=payload.get("request_id", str(uuid.uuid4())),
        )
    except Exception:
        return None


def require_context(token: str, secret: Optional[str] = None) -> ExecutionContext:
    """
    R2: 缺/无效 → 抛 Unauthorized（拒绝且不返回部分结果，防侧信道）。
    """
    if not token:
        raise Unauthorized("缺少 ExecutionContext token")
    ctx = verify_context(token, secret)
    if ctx is None:
        raise Unauthorized("ExecutionContext token 无效或签名不匹配")
    return ctx


def enforce_scope_filter(ctx: ExecutionContext, items: list, scope_key: str) -> list:
    """
    R4: Scope 作为检索入参下推过滤。
    给定 ctx.scopes 与候选条目，返回仅本租户/本 scope 可见者。
    scope_key: items 中用于匹配 scope 的字段名（如 "exhibition_id" 或 "venue_id"）。

    过滤逻辑：
    1. 条目的 tenant_id 必须与 ctx.tenant_id 一致（跨租户隔离）
    2. 如果 ctx.scopes 非空，条目的 scope_key 值必须在 ctx.scopes 范围内
    3. 如果 ctx.scopes 为空，返回该租户下所有条目（租户级权限）
    """
    ctx_scope_ids = set()
    for s in ctx.scopes:
        if ":" in s:
            _, sid = s.split(":", 1)
            ctx_scope_ids.add(sid)

    result = []
    for item in items:
        item_tenant = item.get("tenant_id")
        if item_tenant != ctx.tenant_id:
            continue

        if ctx_scope_ids:
            item_scope_id = item.get(scope_key)
            if item_scope_id and item_scope_id not in ctx_scope_ids:
                continue

        result.append(item)

    return result


def assert_no_caller_supplied_scope(incoming_params: dict, inject_keys: list) -> None:
    """
    RD5: inject_scope_params 必须平台注入，拒绝调用方自传。
    调用方传入 inject_keys 中任意键 → 抛 ForbiddenScopeInjection。
    """
    for key in inject_keys:
        if key in incoming_params and incoming_params[key] is not None:
            raise ForbiddenScopeInjection(
                f"参数 '{key}' 必须由平台注入，调用方不得自传（RD5）"
            )


def is_demo_mode() -> bool:
    """R5: DEMO 模式检测。"""
    return os.getenv("AGENT_MODE") == "DEMO"


def production_ready_label() -> str:
    """R5: DEMO 模式标注「演示环境，非生产」。"""
    if is_demo_mode():
        return "演示环境，非生产"
    return "production"


def record_cross_tenant_attempt(ctx: ExecutionContext, target_tenant: str) -> dict:
    """
    R3: 跨租户访问尝试 100% 审计。
    写独立 JSON 日志（foundation/data/execution_context_audit.json），不污染分析仓。
    """
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request_id": ctx.request_id,
        "user_id": ctx.user_id,
        "source_tenant": ctx.tenant_id,
        "target_tenant": target_tenant,
        "action": "CROSS_TENANT_ATTEMPT",
    }

    append_audit_record(_AUDIT_LOG_PATH, record)

    return record


def get_audit_log() -> list:
    """读取审计日志。"""
    return read_audit_log(_AUDIT_LOG_PATH)


# ---------------------------------------------------------------------------
# F1-D 服务凭证与权限映射（平台访问下游业务系统的机器通道）
# ---------------------------------------------------------------------------
# TODO(F1-D): 接入真实凭证管理后端（如 Vault / KMS）。当前为占位实现，
# 仅返回结构化占位凭证，不读取真实密钥（RD7：凭证/密钥不入代码、不入日志）。


@dataclass
class ServiceCredential:
    """F1-D 平台→下游业务系统的机器通道凭证。

    字段：
        system: 下游系统标识（如 "warehouse" / "iam" / "venue-svc"）
        credential_ref: 凭证引用句柄（非明文密钥，指向外部密钥管理后端）
        permissions: 该凭证授予的权限列表（如 ["read:exhibition", "write:venue"]）
        expires_at: 凭证过期时间（ISO8601，可选）；过期后应拒绝使用
    """

    system: str
    credential_ref: str
    permissions: list = field(default_factory=list)
    expires_at: Optional[str] = None

    def __post_init__(self):
        if not self.system:
            raise ValueError("system 必填")
        if not self.credential_ref:
            raise ValueError("credential_ref 必填（指向外部密钥管理后端，非明文）")


def get_service_credential(system: str) -> "ServiceCredential":
    """F1-D 机器通道凭证获取（**fail-close**）。

    真实凭证后端（Vault/KMS）尚未接入（见 TODO(F1-D)）。在此之前本函数**绝不返回
    占位/真值凭证**——早期实现返回 `credential_ref="placeholder"` 的对象是 truthy，
    一旦被调用方以 `if cred:` 判定放行，即构成 fail-open 越权（审计 P1-8）。
    故显式抛错，强制凭证后端就绪前无法误用本通道。
    """
    # TODO(F1-D): 接入 Vault/KMS 后替换为真实凭证引用读取（返回非占位 ServiceCredential）。
    raise NotImplementedError(
        "服务凭证后端（Vault/KMS）尚未接入；get_service_credential 拒绝返回占位凭证"
        "（fail-close，见审计 arch-audit-2026-09-24.md P1-8）"
    )
