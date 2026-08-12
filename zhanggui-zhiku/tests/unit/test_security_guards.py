# -*- coding: utf-8 -*-
"""
test_security_guards.py —— M5 入站安全护栏单测（方案 §9）。

分层（与 M4 test_tracing 同策略）：
1. **纯逻辑用例（无 web 依赖，CI / 本地无 fastapi 也全绿）**：
   - 统一错误响应体 error_body / error_code_for_status；
   - 入站滑动窗口限流器 SlidingWindowRateLimiter（阈值 / 窗口滑出 / 按 key 隔离 / 线程安全）；
   - 鉴权纯函数（X-API-Key / Bearer 提取、client key 解析、豁免路径判定）；
   - 校验错误文案格式化（含长度上限 / 实际长度）。
2. **web 集成用例（需 fastapi/starlette，skipif 守卫；不连真实服务）**：
   - 用最小 ASGI 应用跑 SecurityGuardsMiddleware：401 / 429 / 413 / health 免鉴权 /
     鉴权关闭语义 / 正常放行 / 响应带 X-Trace-Id 与 request_id；
   - 统一错误响应 {code, msg, request_id} 格式与 X-Trace-Id 一致性。

注意：纯 dict 请求头在测试中使用小写 key（与 starlette Headers 大小写不敏感一致）。
"""

import asyncio
import json
import threading

import pytest

from app.utils.error_response_utils import ERROR_CODES, error_body, error_code_for_status
from app.utils.inbound_rate_limit_utils import SlidingWindowRateLimiter
from app.utils.security_guard_utils import (
    DEFAULT_EXEMPT_PATHS,
    extract_api_key_from_headers,
    format_validation_error,
    resolve_client_key,
    should_skip_all_guards,
    should_skip_auth,
    should_skip_rate_limit,
)

# ---------------------------------------------------------------------------
# web 依赖可用性探测（本地 venv 无 fastapi 时跳过集成用例，CI 全量运行）
# ---------------------------------------------------------------------------
try:
    from starlette.requests import Request  # noqa: F401

    from app.api.errors import error_response, register_exception_handlers
    from app.api.middleware.security_guards import SecurityGuardsMiddleware

    HAVE_WEB = True
except Exception:
    HAVE_WEB = False

requires_web = pytest.mark.skipif(not HAVE_WEB, reason="fastapi/starlette 未安装（web 集成用例跳过）")


# ===========================================================================
# 1) 统一错误响应体（纯逻辑）
# ===========================================================================
def test_error_body_format():
    body = error_body("UNAUTHORIZED", "无效的 API Key", "rid123")
    assert body == {"code": "UNAUTHORIZED", "msg": "无效的 API Key", "request_id": "rid123"}


def test_error_code_for_status():
    assert error_code_for_status(400) == "BAD_REQUEST"
    assert error_code_for_status(401) == "UNAUTHORIZED"
    assert error_code_for_status(413) == "PAYLOAD_TOO_LARGE"
    assert error_code_for_status(429) == "RATE_LIMITED"
    assert error_code_for_status(500) == "INTERNAL_ERROR"
    assert error_code_for_status(599) == "HTTP_ERROR"  # 未登记状态码兜底
    for code in (400, 401, 413, 429, 500):
        assert code in ERROR_CODES


# ===========================================================================
# 2) 入站滑动窗口限流器（纯逻辑）
# ===========================================================================
def test_limiter_allows_under_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    t0 = 1000.0
    assert limiter.allow("k", now=t0) == (True, 0)
    assert limiter.allow("k", now=t0 + 1) == (True, 0)
    assert limiter.allow("k", now=t0 + 2) == (True, 0)


def test_limiter_rejects_over_limit_with_retry_after():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    t0 = 1000.0
    limiter.allow("k", now=t0)
    limiter.allow("k", now=t0 + 1)
    allowed, retry_after = limiter.allow("k", now=t0 + 2)
    assert allowed is False
    # 最早请求 t0 在 t0+60 滑出窗口；now=t0+2 → retry_after ≈ 58（>=1）
    assert 1 <= retry_after <= 60
    assert retry_after == 58  # ceil(1000+60-1002)


def test_limiter_window_expiry_allows_again():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    t0 = 1000.0
    assert limiter.allow("k", now=t0)[0] is True
    assert limiter.allow("k", now=t0 + 1)[0] is False
    # 窗口滑出后恢复放行
    assert limiter.allow("k", now=t0 + 61)[0] is True


def test_limiter_per_key_isolation():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    t0 = 1000.0
    assert limiter.allow("a", now=t0)[0] is True
    assert limiter.allow("a", now=t0 + 1)[0] is False
    assert limiter.allow("b", now=t0 + 1)[0] is True  # 其他 key 不受影响


def test_limiter_reset():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    t0 = 1000.0
    limiter.allow("k", now=t0)
    assert limiter.allow("k", now=t0 + 1)[0] is False
    limiter.reset()
    assert limiter.allow("k", now=t0 + 2)[0] is True
    assert limiter.bucket_size() == 1


def test_limiter_invalid_args():
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=0)
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=5, window_seconds=0)


def test_limiter_thread_safety_smoke():
    """并发调用不抛异常且不超卖（每个 key 窗口内请求数不超过上限）。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
    errors: list = []
    allowed_count = {"n": 0}

    def worker():
        try:
            for _ in range(50):
                ok, _ = limiter.allow("shared")
                if ok:
                    allowed_count["n"] += 1
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # 上限 5 次，4 线程 × 50 次并发，实际放行 ≤ 5（同一窗口内）
    assert allowed_count["n"] <= 5


def test_limiter_sweep_removes_idle_buckets():
    """QA D1 回归：桶数超阈值时，已滑出窗口的 idle 桶被清理。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=1, sweep_threshold=2)
    limiter.allow("k1", now=1.0)
    limiter.allow("k2", now=1.0)
    assert limiter.bucket_size() == 2
    # t=100 加新 key 触发 sweep（桶数 3 > 阈值 2）：k1/k2 最近请求(1.0)已滑出 1s 窗口 → 清理
    limiter.allow("k3", now=100.0)
    assert limiter.bucket_size() == 1
    assert set(limiter._buckets.keys()) == {"k3"}


def test_limiter_sweep_keeps_active_buckets():
    """QA D1 回归：窗口内活跃桶（最近一次请求在窗口内）不被误删。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=10, sweep_threshold=1)
    limiter.allow("k1", now=0.0)
    # t=5 触发 sweep：k1 仍活跃（5-0=5 < 10），k2 刚创建 → 均保留
    limiter.allow("k2", now=5.0)
    assert limiter.bucket_size() == 2
    # t=11 再触发 sweep：k1 已滑出（11-0=11 >= 10）→ 清理；k2 仍活跃（11-5=6 < 10）→ 保留
    limiter.allow("k3", now=11.0)
    assert limiter.bucket_size() == 2
    assert set(limiter._buckets.keys()) == {"k2", "k3"}


def test_limiter_sweep_not_triggered_below_threshold():
    """QA D1 回归：桶数未超阈值时不触发扫描（bucket_size 不变）。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=1, sweep_threshold=5)
    limiter.allow("k1", now=1.0)
    limiter.allow("k2", now=2.0)  # size=2 <= 5，k1 虽已过期但不触发扫描
    assert limiter.bucket_size() == 2
    limiter.allow("k3", now=3.0)
    assert limiter.bucket_size() == 3


# ===========================================================================
# 3) 鉴权纯函数（纯逻辑）
# ===========================================================================
def test_extract_api_key_x_header():
    assert extract_api_key_from_headers({"x-api-key": " abc "}) == "abc"
    assert extract_api_key_from_headers({"x-api-key": "k1"}) == "k1"


def test_extract_api_key_bearer():
    assert extract_api_key_from_headers({"authorization": "Bearer secret123"}) == "secret123"
    assert extract_api_key_from_headers({"authorization": "bearer  abc  "}) == "abc"


def test_extract_api_key_prefers_x_api_key():
    assert extract_api_key_from_headers({"x-api-key": "k1", "authorization": "Bearer k2"}) == "k1"


def test_extract_api_key_missing_or_invalid_scheme():
    assert extract_api_key_from_headers({}) == ""
    assert extract_api_key_from_headers({"authorization": "Basic abc"}) == ""


def test_resolve_client_key():
    # 鉴权启用 + 有 key → key:<sha256>，不明文
    key = resolve_client_key({"x-api-key": "secret"}, "10.0.0.1", auth_enabled=True)
    assert key.startswith("key:")
    assert "secret" not in key
    # 鉴权启用但无 key → ip
    assert resolve_client_key({}, "10.0.0.1", auth_enabled=True) == "ip:10.0.0.1"
    # 鉴权关闭 → 一律按 IP（不信任客户端自报 key）
    assert resolve_client_key({"x-api-key": "secret"}, "10.0.0.2", auth_enabled=False) == "ip:10.0.0.2"
    assert resolve_client_key({}, "", auth_enabled=False) == "ip:unknown"


def test_exempt_paths():
    assert should_skip_all_guards("/health") is True
    assert should_skip_all_guards("/chat.html") is True
    assert should_skip_all_guards("/import.html") is True
    assert should_skip_all_guards("/query") is False
    assert should_skip_auth("/stream/s1") is True  # SSE 免鉴权（EventSource 无法携带自定义头）
    assert should_skip_auth("/query") is False
    assert should_skip_rate_limit("/query") is False
    assert should_skip_rate_limit("/health") is True
    assert DEFAULT_EXEMPT_PATHS == ("/health", "/chat.html", "/import.html")


def test_format_validation_error():
    # 长度超限：含上限与实际长度
    msg = format_validation_error(
        [
            {
                "loc": ("body", "query"),
                "type": "string_too_long",
                "ctx": {"limit_value": 512, "actual_length": 700},
            }
        ]
    )
    assert "长度超限" in msg
    assert "512" in msg
    assert "700" in msg
    # 长度不足
    msg_short = format_validation_error(
        [{"loc": ("body", "query"), "type": "string_too_short", "ctx": {"limit_value": 1}}]
    )
    assert "至少" in msg_short
    # 空错误 → 通用文案
    assert format_validation_error([]) == "请求参数校验失败"


# ===========================================================================
# 4) web 集成（需 fastapi/starlette；最小 ASGI 应用，不连真实服务）
# ===========================================================================
def _build_middleware(middleware_kwargs=None):
    """构造 SecurityGuardsMiddleware 包裹一个返回 200 的哑内层 ASGI 应用。"""
    middleware_kwargs = dict(middleware_kwargs or {})

    async def inner(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"ok": true}'})

    return SecurityGuardsMiddleware(inner, **middleware_kwargs)


def _scope(path, method="POST", headers=None, client=("127.0.0.1", 1234)):
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": client,
        "server": ("testserver", 80),
        "state": {},
    }


def _run(middleware, scope):
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def main():
        await middleware(scope, receive, send)

    asyncio.run(main())
    return messages


def _parse_response(messages):
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in start["headers"]}
    return start["status"], headers, body


@requires_web
def test_error_response_helper():
    resp = error_response(429, "RATE_LIMITED", "too many", "rid1", headers={"Retry-After": "30"})
    assert resp.status_code == 429
    assert resp.headers.get("x-trace-id") == "rid1"
    assert resp.headers.get("retry-after") == "30"
    assert json.loads(resp.body) == {"code": "RATE_LIMITED", "msg": "too many", "request_id": "rid1"}


@requires_web
def test_middleware_passes_normal_request_with_api_key():
    mw = _build_middleware({"api_key": "secret123", "rate_limit_per_client": 100})
    status, headers, body = _parse_response(_run(mw, _scope("/query", headers={"X-API-Key": "secret123"})))
    assert status == 200
    assert "x-trace-id" in headers  # 所有响应统一注入 X-Trace-Id
    assert b'"ok"' in body


@requires_web
def test_middleware_rejects_missing_key():
    mw = _build_middleware({"api_key": "secret123"})
    status, headers, body = _parse_response(_run(mw, _scope("/query")))
    assert status == 401
    payload = json.loads(body)
    assert payload["code"] == "UNAUTHORIZED"
    assert payload["request_id"]
    assert headers.get("x-trace-id") == payload["request_id"]  # 401 也带 X-Trace-Id 且与 body 一致


@requires_web
def test_middleware_rejects_wrong_key():
    mw = _build_middleware({"api_key": "secret123"})
    status, _, body = _parse_response(_run(mw, _scope("/query", headers={"X-API-Key": "wrong"})))
    assert status == 401
    assert json.loads(body)["code"] == "UNAUTHORIZED"


@requires_web
def test_middleware_accepts_bearer_key():
    mw = _build_middleware({"api_key": "secret123"})
    status, _, _ = _parse_response(_run(mw, _scope("/query", headers={"Authorization": "Bearer secret123"})))
    assert status == 200


@requires_web
def test_middleware_auth_disabled_when_no_key_configured():
    # ZHANGUI_API_KEY 为空 → 鉴权关闭，正常放行（向后兼容既有行为）
    mw = _build_middleware({"api_key": ""})
    status, _, _ = _parse_response(_run(mw, _scope("/query")))
    assert status == 200


@requires_web
def test_middleware_health_exempt_and_not_rate_limited():
    mw = _build_middleware({"api_key": "secret123", "rate_limit_per_client": 1})
    # 无 key 也放行（health 免鉴权）
    status, _, _ = _parse_response(_run(mw, _scope("/health")))
    assert status == 200
    # 且不消耗限流配额：再请求仍 200
    status2, _, _ = _parse_response(_run(mw, _scope("/health")))
    assert status2 == 200


@requires_web
def test_middleware_static_page_exempt():
    mw = _build_middleware({"api_key": "secret123"})
    status, _, _ = _parse_response(_run(mw, _scope("/chat.html")))
    assert status == 200
    status2, _, _ = _parse_response(_run(mw, _scope("/import.html")))
    assert status2 == 200


@requires_web
def test_middleware_sse_exempt_auth_but_rate_limited():
    mw = _build_middleware({"api_key": "secret123", "rate_limit_per_client": 2})
    # /stream 免鉴权（无 key 放行）
    assert _parse_response(_run(mw, _scope("/stream/s1")))[0] == 200
    assert _parse_response(_run(mw, _scope("/stream/s2")))[0] == 200
    # 但仍参与限流（同一 IP）：第 3 次 429 + Retry-After
    status, headers, body = _parse_response(_run(mw, _scope("/stream/s3")))
    assert status == 429
    assert "retry-after" in headers
    assert json.loads(body)["code"] == "RATE_LIMITED"


@requires_web
def test_middleware_rate_limit_per_client():
    mw = _build_middleware({"api_key": "secret123", "rate_limit_per_client": 2})
    assert _parse_response(_run(mw, _scope("/query", headers={"X-API-Key": "secret123"})))[0] == 200
    assert _parse_response(_run(mw, _scope("/query", headers={"X-API-Key": "secret123"})))[0] == 200
    status, headers, body = _parse_response(_run(mw, _scope("/query", headers={"X-API-Key": "secret123"})))
    assert status == 429
    assert "retry-after" in headers
    assert json.loads(body)["code"] == "RATE_LIMITED"
    assert json.loads(body)["request_id"]


@requires_web
def test_middleware_payload_too_large():
    mw = _build_middleware({"max_body_bytes": 100, "api_key": ""})
    scope = _scope("/query")
    scope["headers"] = [(b"content-length", b"1000")]
    status, _, body = _parse_response(_run(mw, scope))
    assert status == 413
    assert json.loads(body)["code"] == "PAYLOAD_TOO_LARGE"


@requires_web
def test_middleware_error_response_has_request_id_and_trace():
    mw = _build_middleware({"api_key": "", "rate_limit_per_client": 1})
    _parse_response(_run(mw, _scope("/query")))
    status, headers, body = _parse_response(_run(mw, _scope("/query")))
    assert status == 429
    payload = json.loads(body)
    assert payload["request_id"]
    assert headers.get("x-trace-id") == payload["request_id"]


@requires_web
def test_register_exception_handlers_registers():
    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app = FastAPI()
    register_exception_handlers(app)
    assert RequestValidationError in app.exception_handlers
    assert StarletteHTTPException in app.exception_handlers
    assert Exception in app.exception_handlers
