"""auth.py 单元测试：鉴权与会话策略。"""

import hashlib

import pytest
from fastapi import HTTPException

from app.api.auth import resolve_thread_id, verify_api_key
from app.config import get_settings


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
    _set_api_key(monkeypatch, "secret123")
    expected = f"user-{hashlib.sha256(b'secret123').hexdigest()[:12]}"
    assert resolve_thread_id("client-tid", "secret123") == expected
    assert resolve_thread_id(None, "secret123") == expected


def test_resolve_thread_id_enabled_different_keys_isolate(monkeypatch):
    _set_api_key(monkeypatch, "key-a")
    tid_a = resolve_thread_id("x", "key-a")
    _set_api_key(monkeypatch, "key-b")
    tid_b = resolve_thread_id("x", "key-b")
    assert tid_a != tid_b
