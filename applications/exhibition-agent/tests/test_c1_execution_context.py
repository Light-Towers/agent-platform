"""C1 ExecutionContext 中间件测试（契约 §C1 表）。"""

from __future__ import annotations

import pytest

from exhibition_agent.middleware.context_codec import encode_base64, encode_jwt
from exhibition_agent.middleware.execution_context_middleware import (
    AuthContextInvalidError,
    AuthContextMissingError,
    RequestContextBrokenError,
    ScopeDeniedError,
    resolve_execution_context,
)
from exhibition_agent.testing_helpers import make_context_payload


def test_parse_jwt_success(context_payload):
    header = encode_jwt(context_payload)
    ctx = resolve_execution_context(header, mode="jwt")
    assert ctx.tenant_id == "t-sponsor-001"
    assert ctx.request_id == "req-0001"
    assert ctx.tenant_type.value == "SPONSOR"


def test_parse_base64_success(context_payload):
    header = encode_base64(context_payload)
    ctx = resolve_execution_context(header, mode="base64")
    assert ctx.tenant_id == "t-sponsor-001"


def test_missing_header_raises_401():
    with pytest.raises(AuthContextMissingError) as exc:
        resolve_execution_context(None, mode="jwt")
    assert exc.value.http_status == 401
    assert exc.value.code == "AUTH_CONTEXT_MISSING"


def test_empty_header_raises_401():
    with pytest.raises(AuthContextMissingError):
        resolve_execution_context("   ", mode="jwt")


def test_unparseable_header_raises_401():
    with pytest.raises(AuthContextInvalidError) as exc:
        resolve_execution_context("not.a.valid", mode="jwt")
    assert exc.value.http_status == 401


def test_request_id_missing_raises_400(context_payload):
    payload = {k: v for k, v in context_payload.items() if k != "request_id"}
    header = encode_jwt(payload)
    with pytest.raises(RequestContextBrokenError) as exc:
        resolve_execution_context(header, mode="jwt")
    assert exc.value.http_status == 400


def test_self_reported_tenant_conflict_raises_403(context_payload):
    header = encode_jwt(context_payload)
    with pytest.raises(ScopeDeniedError) as exc:
        resolve_execution_context(
            header,
            mode="jwt",
            self_reported_tenant_id="t-other-999",
        )
    assert exc.value.http_status == 403


def test_empty_scopes_resource_level_raises_403(context_payload):
    payload = make_context_payload(scopes=[])
    header = encode_jwt(payload)
    with pytest.raises(ScopeDeniedError) as exc:
        resolve_execution_context(header, mode="jwt", path="/api/v1/exhibition/ex-001")
    assert exc.value.http_status == 403


def test_empty_scopes_non_resource_level_ok(context_payload):
    payload = make_context_payload(scopes=[])
    header = encode_jwt(payload)
    ctx = resolve_execution_context(header, mode="jwt", path="/api/v1/health")
    assert ctx.tenant_id == "t-sponsor-001"


def test_no_default_tenant_fallback():
    """绝不降级为默认租户：缺头不返回任何 ExecutionContext。"""
    with pytest.raises(AuthContextMissingError):
        resolve_execution_context(None, mode="jwt")


def test_invalid_auth_source_raises_401(context_payload):
    payload = {**context_payload, "auth_source": "UNKNOWN_SOURCE"}
    header = encode_jwt(payload)
    with pytest.raises(AuthContextInvalidError):
        resolve_execution_context(header, mode="jwt")


def test_unknown_mode_raises_401(context_payload):
    header = encode_jwt(context_payload)
    with pytest.raises(AuthContextInvalidError):
        resolve_execution_context(header, mode="xml")


def test_empty_scopes_skill_prefix_resource_level_raises_403(context_payload):
    """v1.1：skill 前缀 venue. + 空 scopes → 403（资源级判定扩展到 skill 前缀）。"""
    payload = make_context_payload(scopes=[])
    header = encode_jwt(payload)
    with pytest.raises(ScopeDeniedError) as exc:
        resolve_execution_context(header, mode="jwt", skill="venue.schedule.query")
    assert exc.value.http_status == 403


def test_empty_scopes_non_resource_skill_ok(context_payload):
    """skill 前缀非 exhibition./venue. + 空 scopes → 放行。"""
    payload = make_context_payload(scopes=[])
    header = encode_jwt(payload)
    ctx = resolve_execution_context(header, mode="jwt", skill="system.health")
    assert ctx.tenant_id == "t-sponsor-001"


def test_roles_empty_allowed(context_payload):
    """v1.1：roles 可留空（角色延后，不参与判定）。"""
    payload = make_context_payload(roles=[])
    header = encode_jwt(payload)
    ctx = resolve_execution_context(header, mode="jwt")
    assert ctx.roles == []
