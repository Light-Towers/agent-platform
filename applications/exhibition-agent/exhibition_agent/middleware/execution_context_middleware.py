"""C1 ExecutionContext 中间件：从 X-Execution-Context 头解析并校验。

严格按契约 v1.1 §C1 表：
- 头缺失 / 不可解析 → 401 AUTH_CONTEXT_MISSING（绝不降级为默认租户）
- 签名无效 / auth_source 不可信 → 401 AUTH_CONTEXT_INVALID
- request_id 缺失 → 400（审计链断裂不允许放行）
- 调用方自报 tenant_id 与 context 冲突 → 403 SCOPE_DENIED
- scopes 为空却访问 exhibition/venue 级资源 → 403 SCOPE_DENIED
  （资源级判定 = 路径含 /exhibition/ 或 /venue/，或 skill 前缀 exhibition. / venue.）

执行档位（v1.1 §C1）：STRICT（验签）/ DEV（不验签），401/403/scope 校验在两档恒开。
本模块不包含任何「按环境跳过校验」的分支 —— mode 仅决定 verify_signature 取值。
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from exhibition_agent.contract.error_codes import ErrorCode
from exhibition_agent.contract.execution_context import ExecutionContext
from exhibition_agent.middleware.context_codec import decode_base64, decode_jwt

EXECUTION_CONTEXT_HEADER: str = "X-Execution-Context"
CONTRACT_VERSION_HEADER: str = "X-Contract-Version"
EXEC_CTX_VERSION: str = "1.1"  # ExecutionContext 规范版本（非联邦查询契约版本，勿与 shared_schemas.CONTRACT_VERSION 混淆）

_RESOURCE_PATH_MARKERS: tuple[str, ...] = ("/exhibition/", "/venue/")
_RESOURCE_SKILL_PREFIXES: tuple[str, ...] = ("exhibition.", "venue.")


class ExecutionContextError(Exception):
    """C1 上下文校验错误基类。"""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"[{code}] {message}")


class AuthContextMissingError(ExecutionContextError):
    def __init__(self, message: str = "X-Execution-Context 头缺失") -> None:
        super().__init__(ErrorCode.AUTH_CONTEXT_MISSING.value, message, 401)


class AuthContextInvalidError(ExecutionContextError):
    def __init__(self, message: str = "上下文不可解析或签名无效") -> None:
        super().__init__(ErrorCode.AUTH_CONTEXT_INVALID.value, message, 401)


class ScopeDeniedError(ExecutionContextError):
    def __init__(self, message: str = "scope 不足或自报 tenant 冲突") -> None:
        super().__init__(ErrorCode.SCOPE_DENIED.value, message, 403)


class RequestContextBrokenError(ExecutionContextError):
    def __init__(self, message: str = "request_id 缺失，审计链断裂") -> None:
        super().__init__(ErrorCode.REQUEST_CONTEXT_BROKEN.value, message, 400)


def execution_mode_to_verify_signature(execution_mode: str) -> bool:
    """执行档位 → 验签开关（契约 v1.1 §C1）。

    STRICT → True（生产，IAM/网关 JWT 验签）
    DEV → False（本地/测试，PLATFORM_LOCAL 不验签）

    注意：此函数**只**返回验签开关；401/403/scope 校验在两档恒开，
    不存在「DEV 跳过校验」的返回值。无 OFF 档。
    """
    mode = execution_mode.upper()
    if mode not in ("STRICT", "DEV"):
        raise ValueError(f"未知执行档位：{execution_mode}（仅支持 STRICT / DEV，无 OFF 档）")
    return mode == "STRICT"


def _is_resource_level(path: str, skill: str | None) -> bool:
    """判断是否为 exhibition/venue 级资源（需 scope）。

    判定规则（契约 v1.1 §C1）：路径含 /exhibition/ 或 /venue/，
    或 skill 名前缀 exhibition. / venue.。
    """
    if any(marker in path for marker in _RESOURCE_PATH_MARKERS):
        return True
    if skill is not None and any(skill.startswith(prefix) for prefix in _RESOURCE_SKILL_PREFIXES):
        return True
    return False


def resolve_execution_context(
    header_value: str | None,
    *,
    mode: str = "jwt",
    path: str = "",
    skill: str | None = None,
    self_reported_tenant_id: str | None = None,
    jwt_secret: str | None = None,
    verify_signature: bool = False,
) -> ExecutionContext:
    """从 X-Execution-Context 头值解析 ExecutionContext 并校验。

    参数：
        header_value: 头原始值；None 表示头缺失。
        mode: "jwt"（默认，D1）或 "base64"（适配器开关）。
        path: 请求路径，用于判断是否 exhibition/venue 级资源。
        skill: skill 名，用于前缀判定资源级（exhibition. / venue.）。
        self_reported_tenant_id: 调用方在 body params.tenant_id 自报的 tenant_id；
            非 None 且与 context.tenant_id 不一致 → 403。
        jwt_secret / verify_signature: JWT 验签参数。
            STRICT 档 verify_signature=True；DEV 档 False。校验逻辑两档恒开。

    返回：校验通过的 ExecutionContext。

    raise：ExecutionContextError 子类（401/403/400），绝不降级。
    """
    if header_value is None or not header_value.strip():
        raise AuthContextMissingError()

    try:
        if mode == "jwt":
            payload: dict[str, Any] = decode_jwt(
                header_value,
                verify_signature=verify_signature,
                secret=jwt_secret,
            )
        elif mode == "base64":
            if verify_signature:
                raise AuthContextInvalidError("STRICT 档禁用无签名的 base64 上下文适配器")
            payload = decode_base64(header_value)
        else:
            raise AuthContextInvalidError(f"未知的上下文传递模式：{mode}")
    except ValueError as exc:
        raise AuthContextInvalidError(str(exc)) from exc

    if "request_id" not in payload or not payload["request_id"]:
        raise RequestContextBrokenError()

    try:
        ctx = ExecutionContext.model_validate(payload)
    except ValidationError as exc:
        raise AuthContextInvalidError(f"上下文字段非法：{exc}") from exc

    if self_reported_tenant_id is not None and self_reported_tenant_id != ctx.tenant_id:
        raise ScopeDeniedError(
            f"自报 tenant_id={self_reported_tenant_id} 与 context.tenant_id={ctx.tenant_id} 冲突"
        )

    if _is_resource_level(path, skill) and not ctx.scopes:
        raise ScopeDeniedError("scopes 为空却访问 exhibition/venue 级资源")

    return ctx
