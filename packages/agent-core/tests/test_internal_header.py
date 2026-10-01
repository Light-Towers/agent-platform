"""agent-core internal_header 原语单测（零依赖、纯 stdlib）。"""

from __future__ import annotations

import pytest

from agent_core.internal_header import (
    InternalHeaderError,
    sign_internal_header,
    verify_internal_header,
)

KEY = b"shared-secret-key"


def test_sign_verify_roundtrip():
    v = sign_internal_header("tenantA", "userB", key=KEY)
    assert verify_internal_header(v, key=KEY, max_age=300) == ("tenantA", "userB")


def test_verify_missing_returns_none():
    assert verify_internal_header(None, key=KEY) is None
    assert verify_internal_header("", key=KEY) is None


def test_forged_signature_rejected():
    v = sign_internal_header("tenantA", None, key=KEY)
    with pytest.raises(InternalHeaderError):
        verify_internal_header(v[:-2] + "ff", key=KEY)


def test_wrong_key_rejected():
    v = sign_internal_header("tenantA", None, key=KEY)
    with pytest.raises(InternalHeaderError):
        verify_internal_header(v, key=b"attacker-key")


def test_expired_rejected():
    v = sign_internal_header("tenantA", None, key=KEY)
    with pytest.raises(InternalHeaderError, match="过期"):
        verify_internal_header(v, key=KEY, max_age=-1)


def test_bad_format_rejected():
    with pytest.raises(InternalHeaderError, match="格式非法"):
        verify_internal_header("not-a-header", key=KEY)


def test_sign_requires_key():
    with pytest.raises(InternalHeaderError):
        sign_internal_header("t", None, key=b"")
