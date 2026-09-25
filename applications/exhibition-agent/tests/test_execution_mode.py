"""执行档位测试（契约 v1.1 §C1：STRICT/DEV，校验恒开，无 OFF 档）。

核心断言：DEV 档仍执行 401/403 与 scope 下推，不存在"测试环境跳过校验"的代码路径。
"""

from __future__ import annotations

import pytest

from exhibition_agent.middleware.execution_context_middleware import (
    AuthContextInvalidError,
    AuthContextMissingError,
    ScopeDeniedError,
    execution_mode_to_verify_signature,
    resolve_execution_context,
)
from exhibition_agent.testing_helpers import ctx, ctx_header


def test_strict_mode_enables_verify_signature():
    assert execution_mode_to_verify_signature("STRICT") is True


def test_dev_mode_disables_verify_signature():
    assert execution_mode_to_verify_signature("DEV") is False


def test_no_off_mode():
    """无 OFF 档：未知档位直接报错，不允许跳过校验。"""
    with pytest.raises(ValueError, match="无 OFF 档"):
        execution_mode_to_verify_signature("OFF")


def test_dev_mode_still_401_on_missing_header():
    """DEV 档：缺头仍 401（不因测试环境跳过）。"""
    with pytest.raises(AuthContextMissingError) as exc:
        resolve_execution_context(None, mode="jwt", verify_signature=False)
    assert exc.value.http_status == 401


def test_dev_mode_still_403_on_empty_scopes_resource_level():
    """DEV 档：空 scopes 访问资源级仍 403（scope 下推恒开）。"""
    context = ctx(scopes=[])
    header = ctx_header(context)
    with pytest.raises(ScopeDeniedError) as exc:
        resolve_execution_context(
            header,
            mode="jwt",
            path="/api/v1/exhibition/ex-001",
            verify_signature=False,
        )
    assert exc.value.http_status == 403


def test_dev_mode_still_403_on_self_reported_tenant_conflict():
    """DEV 档：自报 tenant 冲突仍 403。"""
    context = ctx(tenant_id="t-sponsor-001")
    header = ctx_header(context)
    with pytest.raises(ScopeDeniedError):
        resolve_execution_context(
            header,
            mode="jwt",
            self_reported_tenant_id="t-other-999",
            verify_signature=False,
        )


def test_dev_mode_still_403_on_skill_prefix_resource_level():
    """DEV 档：skill 前缀 venue. + 空 scopes 仍 403。"""
    context = ctx(scopes=[])
    header = ctx_header(context)
    with pytest.raises(ScopeDeniedError):
        resolve_execution_context(
            header,
            mode="jwt",
            skill="venue.schedule.query",
            verify_signature=False,
        )


def test_dev_mode_normal_passes():
    """DEV 档：合法上下文正常放行（校验恒开但不误拦）。"""
    context = ctx()
    header = ctx_header(context)
    result = resolve_execution_context(
        header,
        mode="jwt",
        skill="venue.schedule.query",
        verify_signature=False,
    )
    assert result.tenant_id == context.tenant_id


def test_strict_mode_rejects_base64():
    """STRICT 档禁用无签名 base64 适配器（防验签绕过，INV-8）。"""
    context = ctx()
    header = ctx_header(context, mode="base64")
    with pytest.raises(AuthContextInvalidError, match="STRICT 档禁用无签名") as exc:
        resolve_execution_context(header, mode="base64", verify_signature=True)
    assert exc.value.http_status == 401


def test_dev_mode_allows_base64():
    """DEV 档 base64 适配器仍可用（不验签，校验恒开）。"""
    context = ctx()
    header = ctx_header(context, mode="base64")
    result = resolve_execution_context(
        header,
        mode="base64",
        skill="venue.schedule.query",
        verify_signature=False,
    )
    assert result.tenant_id == context.tenant_id
