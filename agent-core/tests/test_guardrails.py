"""agent_core.guardrails 单元测试。"""

import pytest

from agent_core.guardrails.auth import (
    DEFAULT_EXEMPT_PATHS,
    extract_api_key_from_headers,
    format_validation_error,
    is_health_path,
    resolve_client_key,
    should_skip_all_guards,
    should_skip_auth,
    should_skip_rate_limit,
)
from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
def test_extract_api_key_x_api_key():
    assert extract_api_key_from_headers({"x-api-key": "sk-123"}) == "sk-123"


def test_extract_api_key_bearer():
    assert extract_api_key_from_headers({"authorization": "Bearer sk-456"}) == "sk-456"


def test_extract_api_key_missing():
    assert extract_api_key_from_headers({}) == ""


def test_resolve_client_key_with_auth():
    key = resolve_client_key({"x-api-key": "secret"}, "1.2.3.4", auth_enabled=True)
    assert key.startswith("key:")


def test_resolve_client_key_fallback_ip():
    key = resolve_client_key({}, "1.2.3.4", auth_enabled=False)
    assert key == "ip:1.2.3.4"


def test_resolve_client_key_no_ip():
    key = resolve_client_key({}, None, auth_enabled=False)
    assert key == "ip:unknown"


def test_is_health_path():
    assert is_health_path("/health") is True
    assert is_health_path("/health/ready") is True
    assert is_health_path("/query") is False


def test_should_skip_all_guards():
    assert should_skip_all_guards("/health") is True
    assert should_skip_all_guards("/query") is False


def test_should_skip_auth_sse_exempt():
    assert should_skip_auth("/stream/chat") is True


def test_should_skip_rate_limit_sse_not_exempt():
    assert should_skip_rate_limit("/stream/chat") is False


def test_format_validation_error_string_too_long():
    errors = [{"loc": ("body", "question"), "type": "string_too_long",
               "msg": "too long", "ctx": {"limit_value": 100, "actual_length": 200}}]
    msg = format_validation_error(errors)
    assert "100" in msg and "200" in msg


def test_format_validation_error_empty():
    assert format_validation_error([]) == "请求参数校验失败"


# ---------------------------------------------------------------------------
# ratelimit
# ---------------------------------------------------------------------------
def test_rate_limiter_allows_under_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for i in range(3):
        allowed, _ = limiter.allow(f"client-1", now=1000.0 + i)
        assert allowed is True


def test_rate_limiter_blocks_over_limit():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.allow("c1", now=1000.0)
    limiter.allow("c1", now=1000.1)
    allowed, retry_after = limiter.allow("c1", now=1000.2)
    assert allowed is False
    assert retry_after >= 1


def test_rate_limiter_window_slides():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10)
    limiter.allow("c1", now=100.0)
    limiter.allow("c1", now=100.1)
    allowed, _ = limiter.allow("c1", now=111.0)
    assert allowed is True


def test_rate_limiter_different_keys_independent():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    a1, _ = limiter.allow("client-a", now=1000.0)
    a2, _ = limiter.allow("client-b", now=1000.0)
    assert a1 is True and a2 is True


def test_rate_limiter_reset():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.allow("c1", now=1000.0)
    limiter.reset()
    assert limiter.bucket_size() == 0
