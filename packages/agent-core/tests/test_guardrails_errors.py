# -*- coding: utf-8 -*-
"""agent_core.guardrails.errors / app_factory 单元测试（P2 全局异常 handler）。

- 纯逻辑（error_code_for_status / error_body）零依赖直测；
- build_api_app + 未捕获异常 → 脱敏 500 端到端：需 fastapi + httpx（TestClient），
  缺依赖时 skipif 自动跳过（属设计意图，非失败）。

默认值那一格有**三条**用例共同钉住（D-2=A：4xx/422 不改信封），缺一即留盲区：

1. ``test_http_exception_4xx_detail_unchanged`` —— 行为面：不传参时仍是 ``{detail}``；
2. ``test_factory_and_kernel_defaults_agree`` —— 形状面：工厂与 kernel 两处默认值不得各自漂；
   本轮实踩过 “kernel 改 False 而工厂仍 True” 的半落地态（工厂是所有生产 app 的唯一装配点，
   它的默认值才是生效值）；
3. ``test_legacy_http_envelope_when_normalization_disabled`` —— 降级面：显式传 False 与默认同形。

最终态（``normalize_http_errors=True``）的五条用例**必须显式传参**，不靠默认值蒙对——
“逐 app 显式开启”这条口径的机器面就是那五个 ``True``。
"""

import importlib.util

import pytest

from agent_core.guardrails.errors import (
    ERROR_CODES,
    SANITIZED_5XX_MSG,
    STATUS_MESSAGES,
    AppError,
    error_body,
    error_code_for_status,
    mask_exception_for_client,
    stream_error_frame,
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


def test_error_body_optional_details():
    body = error_body("X", "y", "rid", {"field": "query"})
    assert body["details"] == {"field": "query"}
    assert "details" not in error_body("X", "y", "rid")


def test_error_codes_registered():
    assert ERROR_CODES[503] == "SERVICE_UNAVAILABLE"
    assert ERROR_CODES[422] == "VALIDATION_ERROR"
    assert STATUS_MESSAGES[401] == "未认证或凭据无效"


def test_stream_error_frame_shape():
    assert stream_error_frame("INTERNAL_ERROR", "boom", "rid") == {
        "type": "error",
        "code": "INTERNAL_ERROR",
        "msg": "boom",
        "request_id": "rid",
    }
    assert stream_error_frame("X", "y", "rid", {"step": 1})["details"] == {"step": 1}


# ---------------------------------------------------------------------------
# mask_exception_for_client（P8 堆栈回显收敛的单一脱敏边界点）
# ---------------------------------------------------------------------------
class _RecordingLogger:
    """记录 kernel 写入服务端日志的内容，不往测试输出里报 traceback。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def exception(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


def test_mask_returns_fixed_text():
    assert mask_exception_for_client(ValueError("boom")) == SANITIZED_5XX_MSG


def test_mask_never_leaks_exception_message():
    """对外文案不得含异常消息任何片段（内部路径 / 内网主机 / 上游响应体）。"""
    secret = "/opt/secrets/db.yaml refused host=10.0.0.1"
    out = mask_exception_for_client(RuntimeError(secret))
    assert secret not in out
    assert "10.0.0.1" not in out
    assert "secrets" not in out


def test_mask_message_override_is_business_text():
    """message 允许按业务语义覆盖（但仍是常量文案，不由异常派生）。"""
    fixed = "warehouse 服务不可达，请稍后重试"
    assert mask_exception_for_client(OSError("timed out"), message=fixed) == fixed


def test_mask_logs_full_exception_and_keeps_context():
    log = _RecordingLogger()
    secret = "SELECT * FROM internal_billing failed"
    out = mask_exception_for_client(ValueError(secret), logger=log, context="POST /api/chat")
    assert out == SANITIZED_5XX_MSG
    assert len(log.calls) == 1
    logged = log.calls[0][0][0]
    # context 供人定位；异常消息不拼进日志行（由 logger.exception 自带 traceback）
    assert "POST /api/chat" in logged
    assert secret not in logged


def test_mask_without_logger_is_silent_and_safe():
    """日志已在位的站点（如 loguru 侧）只取固定文案，kernel 不强制接 logger。"""
    assert mask_exception_for_client(KeyError("missing")) == SANITIZED_5XX_MSG


def test_mask_accepts_none_exception():
    """无异常对象也能取到安全文案（退出已丢失 exc 的分支）。"""
    assert mask_exception_for_client(None) == SANITIZED_5XX_MSG


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
def test_app_error_returns_canonical_envelope():
    """``AppError`` 通路**不受 ``normalize_http_errors`` 管**（本用例不传该参 = 默认 False）。

    所以它同时是方案 §4 第 2 条的反证载体：把 ``install_error_handlers`` 里那行
    ``app.add_exception_handler(AppError, ...)`` 挪进开关体内或删掉 ⇒ 本条当场红。
    """
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", get_request_id=lambda: "req-app", logger=_NullLogger())

    @app.get("/denied")
    def _denied():
        raise AppError(403, "SCOPE_DENIED", "无权访问该资源", details={"scope": "venue"})

    resp = TestClient(app, raise_server_exceptions=False).get("/denied")
    assert resp.status_code == 403
    assert resp.json() == {
        "code": "SCOPE_DENIED",
        "msg": "无权访问该资源",
        "request_id": "req-app",
        "details": {"scope": "venue"},
    }
    assert resp.headers.get("x-trace-id") == "req-app"


@requires_web
def test_app_error_5xx_keeps_server_declared_message():
    """5xx 的**脱敏射程是未捕获异常**，不是服务端自己声明的常量文案（方案 §3.1）。

    登录面有八处 ``AppError(503, …, "登录未启用：…")``：那些文案是唯一能把「部署被改坏」
    与「用户输错」分开的线索。把它们一起抹成通用句 = 运维面自毁（客户端与日志同报一句
    「服务器内部错误」）。真含内部信息的东西本就不该写进 ``msg``——这条边界靠本用例钉。
    反向一格：``details`` 仍按状态码收，5xx 一律不带出。
    """
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", get_request_id=lambda: "req-503b", logger=_NullLogger())

    @app.get("/login")
    def _login():
        raise AppError(
            503,
            "AUTH_SIGNER_UNAVAILABLE",
            "登录未启用：签名密钥未在位",
            details={"reason": "TENANT_JWT_PRIVATE_KEY_FILE missing"},
        )

    resp = TestClient(app, raise_server_exceptions=False).get("/login")
    body = resp.json()
    assert resp.status_code == 503
    assert body["code"] == "AUTH_SIGNER_UNAVAILABLE"
    assert body["msg"] == "登录未启用：签名密钥未在位"
    assert body["msg"] != SANITIZED_5XX_MSG
    # details 不外带（结构化上下文泄面高于文案），request_id 与头仍成对
    assert "details" not in body
    assert "TENANT_JWT_PRIVATE_KEY_FILE" not in resp.text
    assert body["request_id"] == "req-503b" == resp.headers.get("x-trace-id")


@requires_web
def test_http_exception_4xx_detail_unchanged():
    """D-2=A：仅兜底 Exception→500，4xx HTTPException 仍走 FastAPI 默认 {detail} 信封。

    **不传 ``normalize_http_errors`` 是这条用例的要点**：它钉的就是默认值。把工厂或 kernel
    的默认翻成 True ⇒ 本条必红（翻默认值 = 存量对外形状变更，是 D2 决策，不能随实现漂）。
    """
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t", logger=_NullLogger())

    @app.get("/bad")
    def _bad():
        raise HTTPException(status_code=400, detail="bad input")

    resp = TestClient(app, raise_server_exceptions=False).get("/bad")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "bad input"}


def test_factory_and_kernel_defaults_agree():
    """工厂与 kernel 的 ``normalize_http_errors`` 默认值必须同值（签名形状直测，不需 fastapi）。

    为什么不靠上面那条行为用例一并遮住：行为用例只经过**工厂**，它读不到 kernel 自己的默认。
    11-06 本轮实踩：kernel 改成 False 而工厂仍 True ——两个默认值 disagree 时，生效的是工厂那个
    （它是所有生产 app 的唯一装配点），而读代码的人会按 kernel 的签名理解系统。
    """
    import inspect

    from agent_core.guardrails.app_factory import build_api_app
    from agent_core.guardrails.errors import install_error_handlers

    factory_default = inspect.signature(build_api_app).parameters[
        "normalize_http_errors"
    ].default
    kernel_default = inspect.signature(install_error_handlers).parameters[
        "normalize_http_errors"
    ].default
    assert factory_default is kernel_default is False, (
        f"两处默认值不同值或不是 False（工厂={factory_default!r} / kernel={kernel_default!r}）"
        "⇒ 要么有人在翻默认值（D-2=A 存量变更，须先拍板），要么只改了一半"
    )


@requires_web
def test_http_exception_4xx_uses_canonical_envelope():
    """最终态（**显式开启**）：HTTPException(4xx) 归一到 {code,msg,request_id}。"""
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(
        title="t",
        get_request_id=lambda: "req-400",
        logger=_NullLogger(),
        normalize_http_errors=True,
    )

    @app.get("/bad")
    def _bad():
        raise HTTPException(status_code=400, detail="bad input")

    resp = TestClient(app, raise_server_exceptions=False).get("/bad")
    assert resp.status_code == 400
    assert resp.json() == {
        "code": "BAD_REQUEST",
        "msg": "bad input",
        "request_id": "req-400",
    }


@requires_web
def test_http_exception_machine_token_gets_human_message():
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(
        title="t",
        get_request_id=lambda: "req-429",
        logger=_NullLogger(),
        normalize_http_errors=True,
    )

    @app.get("/budget")
    def _budget():
        raise HTTPException(status_code=429, detail="BUDGET_EXCEEDED")

    body = TestClient(app, raise_server_exceptions=False).get("/budget").json()
    assert body["code"] == "BUDGET_EXCEEDED"
    assert body["msg"] == STATUS_MESSAGES[429]


@requires_web
def test_http_exception_dict_is_normalized():
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(
        title="t",
        get_request_id=lambda: "req-dict",
        logger=_NullLogger(),
        normalize_http_errors=True,
    )

    @app.get("/auth")
    def _auth():
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_CONTEXT_INVALID", "message": "身份上下文无效"},
        )

    body = TestClient(app, raise_server_exceptions=False).get("/auth").json()
    assert body == {
        "code": "AUTH_CONTEXT_INVALID",
        "msg": "身份上下文无效",
        "request_id": "req-dict",
    }


@requires_web
def test_explicit_5xx_http_exception_is_sanitized():
    """**未走 ``AppError``** 的显式 HTTPException(5xx) 仍抹文案。

    与 ``test_app_error_5xx_keeps_server_declared_message`` 是一对此消彼长的判据：
    抹不抹取决于「这句话是不是服务端自己声明的常量」，不取决于状态码大小。
    ``HTTPException(detail=…)`` 的 detail 在存量代码里什么都可能装（含上游响应体），
    所以归一化通路对 5xx 保守；``AppError.msg`` 是类型保证的常量，所以保留。
    """
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(
        title="t",
        get_request_id=lambda: "req-503",
        logger=_NullLogger(),
        normalize_http_errors=True,
    )

    @app.get("/full")
    def _full():
        raise HTTPException(
            status_code=503,
            detail={"code": "SCHEDULER_SLOTS_EXHAUSTED", "message": "db=/opt/private"},
        )

    body = TestClient(app, raise_server_exceptions=False).get("/full").json()
    assert body["code"] == "SCHEDULER_SLOTS_EXHAUSTED"
    assert body["msg"] == SANITIZED_5XX_MSG
    assert "db=/opt/private" not in str(body)


@requires_web
def test_validation_error_returns_canonical_422_without_input():
    from fastapi.testclient import TestClient
    from pydantic import BaseModel

    from agent_core.guardrails.app_factory import build_api_app

    class _Message(BaseModel):
        role: str
        content: str

    class _Payload(BaseModel):
        messages: list[_Message]

    app = build_api_app(
        title="t",
        get_request_id=lambda: "req-422",
        logger=_NullLogger(),
        normalize_http_errors=True,
    )

    @app.post("/validate")
    def _validate(payload: _Payload):
        return {"ok": True}

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/validate", json={"messages": [{"role": "user"}]}
    )
    body = resp.json()
    assert resp.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert body["request_id"] == "req-422"
    assert body["details"]
    assert "input" not in body["details"][0]
    assert body["details"][0]["loc"][-1] == "content"


@requires_web
def test_legacy_http_envelope_when_normalization_disabled():
    """降级面：显式传 False 与默认同形（与不传参那条各钉一个失效口：默认被翻 / 参被删）。"""
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(
        title="t",
        logger=_NullLogger(),
        normalize_http_errors=False,
    )

    @app.get("/legacy")
    def _legacy():
        raise HTTPException(status_code=400, detail="bad input")

    assert TestClient(app, raise_server_exceptions=False).get("/legacy").json() == {
        "detail": "bad input"
    }


# ---------------------------------------------------------------------------
# R19：build_api_app 默认关闭 FastAPI 原生 telemetry
# （docs/plans/plan-r19-fastapi-native-telemetry-2026-10-19.md）
# ---------------------------------------------------------------------------


def test_build_api_app_defaults_native_telemetry_off(monkeypatch):
    """工厂默认传 telemetry={"tracing": False}（spy 验证调用形状，版本无关）。

    FastAPI <0.142 静默吞该 kwarg（无效果也无错），≥0.142 才真正消费 ⇒ 断言
    「调用形状」而非 app 属性，任何已安装版本上都是同一判据。
    """
    import fastapi

    from agent_core.guardrails.app_factory import build_api_app

    seen: dict = {}

    class _SpyFastAPI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def add_exception_handler(self, *args, **kwargs):
            pass

    monkeypatch.setattr(fastapi, "FastAPI", _SpyFastAPI)
    build_api_app(title="t")
    assert seen.get("telemetry") == {"tracing": False}


def test_build_api_app_caller_can_override_telemetry(monkeypatch):
    """setdefault 不剥夺覆盖权：调用方显式传 telemetry 时工厂不得改写。"""
    import fastapi

    from agent_core.guardrails.app_factory import build_api_app

    seen: dict = {}

    class _SpyFastAPI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def add_exception_handler(self, *args, **kwargs):
            pass

    monkeypatch.setattr(fastapi, "FastAPI", _SpyFastAPI)
    build_api_app(title="t", telemetry={"tracing": True})
    assert seen.get("telemetry") == {"tracing": True}


@requires_web
def test_build_api_app_real_construction_smoke():
    """真实 fastapi 上构造不炸（telemetry kwarg 在当前版本被接受）。"""
    from agent_core.guardrails.app_factory import build_api_app

    app = build_api_app(title="t")
    assert app.title == "t"
