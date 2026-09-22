"""F01 Foundation ExecutionContext 合并后功能测试。

覆盖：
- tenant_type 枚举含 VENUE_OPERATOR（contract + foundation 同步）
- R3 跨租户访问审计记录写入
- R5 DEMO/SANDBOX 模式标注
- F1-D 服务凭证占位
- 现有功能不破坏（HMAC 签名/验签、R4 scope 下推、RD5 自传拦截）
"""

from __future__ import annotations

import json
import os

import pytest

from exhibition_agent.contract.execution_context import ExecutionContext, TenantType
from exhibition_agent.foundation.execution_context import (
    VALID_AUTH_SOURCES,
    VALID_TENANT_TYPES,
    ExecutionContext as FoundationExecutionContext,
    ForbiddenScopeInjection,
    ServiceCredential,
    Unauthorized,
    assert_no_caller_supplied_scope,
    enforce_scope_filter,
    get_audit_log,
    get_service_credential,
    is_demo_mode,
    production_ready_label,
    record_cross_tenant_attempt,
    require_context,
    sign_context,
    verify_context,
)


# ---------------------------------------------------------------------------
# tenant_type 枚举含 VENUE_OPERATOR
# ---------------------------------------------------------------------------


class TestTenantTypeVenueOperator:
    def test_contract_enum_has_venue_operator(self):
        assert TenantType.VENUE_OPERATOR == "VENUE_OPERATOR"
        assert "VENUE_OPERATOR" in {t.value for t in TenantType}

    def test_foundation_valid_set_has_venue_operator(self):
        assert "VENUE_OPERATOR" in VALID_TENANT_TYPES

    def test_contract_model_accepts_venue_operator(self):
        ctx = ExecutionContext(
            user_id="u-001",
            tenant_id="t-vo-001",
            tenant_type=TenantType.VENUE_OPERATOR,
            auth_source="PLATFORM_LOCAL",
            request_id="req-vo-001",
        )
        assert ctx.tenant_type == TenantType.VENUE_OPERATOR

    def test_foundation_dataclass_accepts_venue_operator(self):
        ctx = FoundationExecutionContext(
            user_id="u-001",
            tenant_id="t-vo-001",
            tenant_type="VENUE_OPERATOR",
        )
        assert ctx.tenant_type == "VENUE_OPERATOR"

    def test_foundation_rejects_invalid_tenant_type(self):
        with pytest.raises(ValueError, match="tenant_type"):
            FoundationExecutionContext(
                user_id="u-001",
                tenant_id="t-001",
                tenant_type="INVALID_TYPE",
            )


# ---------------------------------------------------------------------------
# R3 跨租户访问审计记录
# ---------------------------------------------------------------------------


class TestCrossTenantAudit:
    def test_record_cross_tenant_attempt_writes_audit(
        self, tmp_path, monkeypatch
    ):
        audit_path = tmp_path / "audit.json"
        monkeypatch.setattr(
            "exhibition_agent.foundation.execution_context._AUDIT_LOG_PATH",
            str(audit_path),
        )

        ctx = FoundationExecutionContext(
            user_id="u-auditor",
            tenant_id="t-source",
            tenant_type="SPONSOR",
            request_id="req-audit-001",
        )

        record = record_cross_tenant_attempt(ctx, target_tenant="t-target")

        assert record["request_id"] == "req-audit-001"
        assert record["user_id"] == "u-auditor"
        assert record["source_tenant"] == "t-source"
        assert record["target_tenant"] == "t-target"
        assert record["action"] == "CROSS_TENANT_ATTEMPT"
        assert "timestamp" in record

        assert audit_path.exists()
        log = json.loads(audit_path.read_text("utf-8"))
        assert len(log) == 1
        assert log[0]["request_id"] == "req-audit-001"

    def test_record_cross_tenant_appends_existing_log(
        self, tmp_path, monkeypatch
    ):
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(
            json.dumps([{"existing": True}]), encoding="utf-8"
        )
        monkeypatch.setattr(
            "exhibition_agent.foundation.execution_context._AUDIT_LOG_PATH",
            str(audit_path),
        )

        ctx = FoundationExecutionContext(
            user_id="u-002",
            tenant_id="t-a",
            tenant_type="VENUE",
            request_id="req-audit-002",
        )
        record_cross_tenant_attempt(ctx, target_tenant="t-b")

        log = get_audit_log()
        assert len(log) == 2
        assert log[0]["existing"] is True
        assert log[1]["request_id"] == "req-audit-002"

    def test_get_audit_log_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "exhibition_agent.foundation.execution_context._AUDIT_LOG_PATH",
            str(tmp_path / "nonexistent.json"),
        )
        assert get_audit_log() == []


# ---------------------------------------------------------------------------
# R5 DEMO/SANDBOX 模式标注
# ---------------------------------------------------------------------------


class TestDemoModeLabel:
    def test_is_demo_mode_false_by_default(self, monkeypatch):
        monkeypatch.delenv("AGENT_MODE", raising=False)
        assert is_demo_mode() is False

    def test_is_demo_mode_true_when_env_set(self, monkeypatch):
        monkeypatch.setenv("AGENT_MODE", "DEMO")
        assert is_demo_mode() is True

    def test_production_ready_label_production(self, monkeypatch):
        monkeypatch.delenv("AGENT_MODE", raising=False)
        assert production_ready_label() == "production"

    def test_production_ready_label_demo(self, monkeypatch):
        monkeypatch.setenv("AGENT_MODE", "DEMO")
        assert production_ready_label() == "演示环境，非生产"


# ---------------------------------------------------------------------------
# F1-D 服务凭证占位
# ---------------------------------------------------------------------------


class TestServiceCredentialPlaceholder:
    def test_get_service_credential_returns_placeholder(self):
        cred = get_service_credential("warehouse")
        assert isinstance(cred, ServiceCredential)
        assert cred.system == "warehouse"
        assert cred.credential_ref == "placeholder"
        assert cred.permissions == []
        assert cred.expires_at is None

    def test_service_credential_requires_system(self):
        with pytest.raises(ValueError, match="system"):
            ServiceCredential(system="", credential_ref="ref")

    def test_service_credential_requires_credential_ref(self):
        with pytest.raises(ValueError, match="credential_ref"):
            ServiceCredential(system="warehouse", credential_ref="")


# ---------------------------------------------------------------------------
# 现有功能不破坏：HMAC 签名 / 验签
# ---------------------------------------------------------------------------


class TestHmacSignature:
    def test_sign_and_verify_roundtrip(self, monkeypatch):
        monkeypatch.setenv("F01_SIGNING_SECRET", "test-secret-key")

        ctx = FoundationExecutionContext(
            user_id="u-sign",
            tenant_id="t-sign",
            tenant_type="SPONSOR",
            request_id="req-sign-001",
        )
        token = sign_context(ctx)
        assert "." in token

        recovered = verify_context(token)
        assert recovered is not None
        assert recovered.user_id == "u-sign"
        assert recovered.tenant_id == "t-sign"
        assert recovered.request_id == "req-sign-001"

    def test_verify_rejects_tampered_token(self, monkeypatch):
        monkeypatch.setenv("F01_SIGNING_SECRET", "test-secret-key")

        ctx = FoundationExecutionContext(
            user_id="u-tamper",
            tenant_id="t-tamper",
            tenant_type="VENUE",
            request_id="req-tamper",
        )
        token = sign_context(ctx)
        tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
        assert verify_context(tampered) is None

    def test_require_context_raises_on_empty(self):
        with pytest.raises(Unauthorized):
            require_context("")

    def test_require_context_raises_on_invalid(self, monkeypatch):
        monkeypatch.setenv("F01_SIGNING_SECRET", "test-secret-key")
        with pytest.raises(Unauthorized):
            require_context("invalid.token")

    def test_sign_context_venue_operator(self, monkeypatch):
        monkeypatch.setenv("F01_SIGNING_SECRET", "test-secret-key")
        ctx = FoundationExecutionContext(
            user_id="u-vo",
            tenant_id="t-vo",
            tenant_type="VENUE_OPERATOR",
            request_id="req-vo",
        )
        token = sign_context(ctx)
        recovered = verify_context(token)
        assert recovered is not None
        assert recovered.tenant_type == "VENUE_OPERATOR"


# ---------------------------------------------------------------------------
# 现有功能不破坏：R4 scope 下推过滤
# ---------------------------------------------------------------------------


class TestEnforceScopeFilter:
    def _make_ctx(self, **kwargs):
        defaults = dict(
            user_id="u-001",
            tenant_id="t-001",
            tenant_type="SPONSOR",
            scopes=["exhibition:ex-001", "venue:vn-001"],
            request_id="req-001",
        )
        defaults.update(kwargs)
        return FoundationExecutionContext(**defaults)

    def test_filters_other_tenant_items(self):
        ctx = self._make_ctx()
        items = [
            {"tenant_id": "t-001", "exhibition_id": "ex-001"},
            {"tenant_id": "t-002", "exhibition_id": "ex-002"},
        ]
        result = enforce_scope_filter(ctx, items, scope_key="exhibition_id")
        assert len(result) == 1
        assert result[0]["tenant_id"] == "t-001"

    def test_filters_by_scope_id(self):
        ctx = self._make_ctx(scopes=["exhibition:ex-001"])
        items = [
            {"tenant_id": "t-001", "exhibition_id": "ex-001"},
            {"tenant_id": "t-001", "exhibition_id": "ex-999"},
        ]
        result = enforce_scope_filter(ctx, items, scope_key="exhibition_id")
        assert len(result) == 1
        assert result[0]["exhibition_id"] == "ex-001"

    def test_empty_scopes_returns_all_tenant_items(self):
        ctx = self._make_ctx(scopes=[])
        items = [
            {"tenant_id": "t-001", "exhibition_id": "ex-001"},
            {"tenant_id": "t-001", "exhibition_id": "ex-002"},
            {"tenant_id": "t-002", "exhibition_id": "ex-003"},
        ]
        result = enforce_scope_filter(ctx, items, scope_key="exhibition_id")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 现有功能不破坏：RD5 调用方自传拦截
# ---------------------------------------------------------------------------


class TestAssertNoCallerSuppliedScope:
    def test_passes_when_key_absent(self):
        assert_no_caller_supplied_scope({"foo": 1}, inject_keys=["scope_param"])

    def test_passes_when_key_none(self):
        assert_no_caller_supplied_scope(
            {"scope_param": None}, inject_keys=["scope_param"]
        )

    def test_raises_when_key_present(self):
        with pytest.raises(ForbiddenScopeInjection, match="scope_param"):
            assert_no_caller_supplied_scope(
                {"scope_param": "evil"}, inject_keys=["scope_param"]
            )
