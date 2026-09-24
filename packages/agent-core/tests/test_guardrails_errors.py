# -*- coding: utf-8 -*-
"""agent_core.guardrails.errors / app_factory 单元测试（P2 全局异常 handler）。

- 纯逻辑（error_code_for_status / error_body）零依赖直测；
- build_api_app + 未捕获异常 → 脱敏 500 端到端：需 fastapi + httpx（TestClient），
  缺依赖时 skipif 自动跳过（属设计意图，非失败）。
"""

import importlib.util

import pytest

from agent_core.guardrails.errors import (
    ERROR_CODES,
    SANITIZED_5XX_MSG,
    error_body,
    error_code_for_status,
)

_has_fastapi = importlib.util.find_spec("fastapi") is not None
_has_httpx = importlib.util.find_spec("httpx") is not None
requires_web = pytest.mark.skipif(
    not (_has_fastapi and _has_httpx), reason="需要 fastapi + httpx（TestClient）"
)


class _NullLogger:
    """吞掉 handler 的 log.exception，避免测试噪声。"""

    def exception(self, *args, **kwargs):
        pass


# ---------------------------------------------------------------------------
# 纯逻辑
# ---------------------------------------------------------------------------
def test_error_code_for_status_known():
    assert error_code_for_status(500) == "INTERNAL_ERROR"
    assert error_code_for_status(429) == "RATE_LIMITED"


def test_error_code_for_status_unknown_falls_back():
    assert error_code_for_status(418) == "HTTP_ERROR"


def test_error_body_shape():
    assert error_body("INTERNAL_ERROR", "boom", "rid") == {
        "code": "INTERNAL_ERROR",
        "msg": "boom",
        "request_id": "rid",
    }


def test_error_body_request_id_empty():
    assert error_body("X", "y", "")["request_id"] == ""


def test_error_codes_registered():
    assert ERROR_CODES[503] == "SERVICE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# app_factory + 未捕获异常端到端
# ---------------------------------------------------------------------------
@requires_web
def test_build_api_app_registers_exception_handler():
    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", logger=_NullLogger())
    assert Exception in app.exception_handlers


@requires_web
def test_build_api_app_install_handlers_false():
    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", install_handlers=False)
    assert Exception not in app.exception_handlers


@requires_web
def test_unhandled_exception_returns_sanitized_500():
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", get_request_id=lambda: "req-fixed", logger=_NullLogger())

    @app.get("/boom")
    def _boom():
        raise RuntimeError("secret internal detail /home/user/private.py")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["msg"] == SANITIZED_5XX_MSG
    assert body["request_id"] == "req-fixed"
    assert resp.headers.get("x-trace-id") == "req-fixed"
    # 脱敏：原始异常详情 / 堆栈 / 内部路径不得外泄
    text = resp.text
    assert "secret internal detail" not in text
    assert "Traceback" not in text
    assert "/home/user" not in text


@requires_web
def test_http_exception_4xx_detail_unchanged():
    """D-2=A：仅兜底 Exception→500，4xx HTTPException 仍走 FastAPI 默认 {detail} 信封。"""
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", logger=_NullLogger())

    @app.get("/bad")
    def _bad():
        raise HTTPException(status_code=400, detail="bad input")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/bad")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "bad input"}
