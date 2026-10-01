"""auth.py 单元测试：鉴权与会话策略。"""

import hashlib

import pytest
from agent_core.guardrails.auth import ENV_SECURITY_PEPPER, derive_thread_id
from agent_server.api.auth import resolve_thread_id, verify_api_key
from agent_server.config import get_settings
from fastapi import HTTPException


def _set_api_key(monkeypatch, key: str):
    monkeypatch.setenv("API_KEY", key)
    get_settings.cache_clear()


def test_verify_api_key_disabled_returns_none(monkeypatch):
    _set_api_key(monkeypatch, "")
    assert verify_api_key(None) is None
    assert verify_api_key("any") is None


def test_verify_api_key_enabled_correct(monkeypatch):
    _set_api_key(monkeypatch, "secret123")
    assert verify_api_key("secret123") == "secret123"


def test_verify_api_key_enabled_wrong_raises_401(monkeypatch):
    _set_api_key(monkeypatch, "secret123")
    with pytest.raises(HTTPException) as exc:
        verify_api_key("wrong")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        verify_api_key(None)
    assert exc.value.status_code == 401


def test_resolve_thread_id_disabled_trusts_client(monkeypatch):
    _set_api_key(monkeypatch, "")
    assert resolve_thread_id("client-tid", None) == "client-tid"
    assert resolve_thread_id(None, None) == "dev-default-thread"


def test_resolve_thread_id_enabled_derives_from_key(monkeypatch):
    """DUP-1 收敛后的契约：会话身份由 kernel fingerprint 单一实现派生，且不再是旧 48bit 裸哈希。"""
    _set_api_key(monkeypatch, "secret123")
    monkeypatch.delenv(ENV_SECURITY_PEPPER, raising=False)
    expected = derive_thread_id("secret123")
    assert resolve_thread_id("client-tid", "secret123") == expected
    assert resolve_thread_id(None, "secret123") == expected
    # 旧实现（裸 sha256 前 12 hex = 48bit）必须已被替换
    assert expected != f"user-{hashlib.sha256(b'secret123').hexdigest()[:12]}"
    assert len(expected) == len("user-") + 32  # 128bit


def test_resolve_thread_id_enabled_different_keys_isolate(monkeypatch):
    _set_api_key(monkeypatch, "key-a")
    tid_a = resolve_thread_id("x", "key-a")
    _set_api_key(monkeypatch, "key-b")
    tid_b = resolve_thread_id("x", "key-b")
    assert tid_a != tid_b
