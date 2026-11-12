"""agent-core internal_header 原语单测（零依赖、纯 stdlib）。"""

from __future__ import annotations

import pytest

from agent_core.internal_header import (
    InternalHeaderError,
    sign_internal_header,
    verify_internal_header,
    verify_internal_header_with_role,
)

KEY = b"shared-secret-key"


def test_sign_verify_roundtrip():
    v = sign_internal_header("tenantA", "userB", key=KEY)
    assert verify_internal_header(v, key=KEY, max_age=300) == ("tenantA", "userB")


def test_roundtrip_with_role():
    """1c/D11：带 r 的头经三元组验签拿到 role。"""
    v = sign_internal_header("tenantA", "userB", key=KEY, role="admin")
    assert verify_internal_header_with_role(v, key=KEY) == ("tenantA", "userB", "admin")


def test_legacy_header_has_no_role():
    """旧签发方（无 r 键）⇒ role=None，消费侧按最小权限处置（fail-closed）。"""
    v = sign_internal_header("tenantA", "userB", key=KEY)
    assert verify_internal_header_with_role(v, key=KEY) == ("tenantA", "userB", None)


def test_legacy_verifier_ignores_role_key():
    """F17 兼容自证：旧验签方用二元组读带 r 的新头，行为逐字不变。"""
    v = sign_internal_header("tenantA", "userB", key=KEY, role="admin")
    assert verify_internal_header(v, key=KEY) == ("tenantA", "userB")


def test_tampered_role_is_rejected():
    """合成违规：换 payload 里的 r 却沿用旧签名 ⇒ 签名不符，不静默提权。"""
    v = sign_internal_header("tenantA", "userB", key=KEY, role="viewer")
    forged = sign_internal_header("tenantA", "userB", key=KEY, role="admin")
    assert forged != v
    parts, forged_parts = v.split("."), forged.split(".")
    with pytest.raises(InternalHeaderError):
        verify_internal_header_with_role(
            f"{parts[0]}.{forged_parts[1]}.{parts[2]}", key=KEY
        )


def test_verify_missing_returns_none():
    assert verify_internal_header(None, key=KEY) is None
    assert verify_internal_header("", key=KEY) is None


def test_forged_signature_rejected():
    v = sign_internal_header("tenantA", None, key=KEY)
    # 只破坏签名尾部 2 个 hex（payload/格式保持合法），且**按构造保证伪造串 != 合法串**：
    # 旧写法固定换成 "ff"，而签名含时间戳每秒一变，真签名末尾恰为 "ff" 时
    # forged == val ⇒ verify 正常返回，属 1/256 概率假失败（实测 1/261，docs/TODO.md 已登记）。
    tail = "11" if v.endswith("00") else "00"
    forged = v[:-2] + tail
    assert forged != v, "伪造串与合法串相同 ⇒ 本用例没在校验签名，判据失效"
    with pytest.raises(InternalHeaderError):
        verify_internal_header(forged, key=KEY)


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
