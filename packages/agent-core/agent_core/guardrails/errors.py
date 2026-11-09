# -*- coding: utf-8 -*-
"""入站统一错误契约 / 异常处理器（最终态：{code,msg,request_id,[details]}）。

从 ``knowledge_service.utils.error_response_utils`` 上提到 kernel，供全仓共享，
与 ``agent_core.guardrails.web``（SecurityGuardsMiddleware）同属**入站横切层**——
错误处理是这一层的另一面。

分层：
- 纯逻辑（``AppError`` / ``ERROR_CODES`` / ``error_code_for_status`` / ``error_body`` /
  ``stream_error_frame`` / ``mask_exception_for_client``）零第三方依赖，
  仅装 stdlib 的 venv 也能 import、可独立单测；
- ``make_error_response`` / ``install_error_handlers`` 需要的 starlette 为**函数内懒导入**
  （``web`` extra），保持本模块可无 starlette 导入。

最终态：所有 HTTP 错误出口（4xx/5xx、显式 ``HTTPException``、校验错误、未捕获异常）
统一为 ``{"code": ..., "msg": ..., "request_id": ..., "details": ...?}``；流式错误帧统一为
``{"type": "error", "code": ..., "msg": ..., "request_id": ..., "details": ...?}``。
不再输出 ``detail`` / ``error`` / ``error_code`` / ``error_class``。迁移期若仍需旧键
（例如未升级的前端），由调用方在边界显式适配，不进入 kernel 默认契约。

**上面那一段是最终态，不是当前默认态。** 默认（``normalize_http_errors=False``，工厂同值）只做到：
未捕获 ``Exception → 500`` 脱敏信封 + ``AppError`` 通路；各 app 现有的 4xx/422 仍是 FastAPI 原生
``{detail}``。把前者当后者来读会让人按统一信封去写消费者而现网落空（在册决定 D-2=A，
钉住默认值的是 ``tests/test_guardrails_errors.py::test_http_exception_4xx_detail_unchanged``
与 ``::test_factory_and_kernel_defaults_agree``，分阶段口径见
``docs/plans/plan-error-contract-staged-split-2026-11-06.md``）。
"""

from __future__ import annotations

import contextlib
import re
from typing import Any, Callable, Dict, Optional, Sequence

from agent_core.logging import get_logger

# 未捕获异常对外统一脱敏文案（详情仅入服务端日志，不外泄堆栈/内部路径/密钥）。
SANITIZED_5XX_MSG = "服务器内部错误，请稍后重试"

# 状态码 → 机器可读错误码（对外稳定，便于客户端程序化处理；不泄露内部细节）。
ERROR_CODES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}

# 状态码 → 缺省对外文案（机器 token 不能直接当用户文案）。
STATUS_MESSAGES: Dict[int, str] = {
    400: "请求参数有误",
    401: "未认证或凭据无效",
    403: "无权访问该资源",
    404: "资源不存在",
    405: "请求方法不允许",
    409: "请求冲突，请稍后重试",
    413: "请求体过大",
    422: "请求参数校验失败",
    429: "请求过于频繁，请稍后重试",
    500: SANITIZED_5XX_MSG,
    502: "上游服务异常，请稍后重试",
    503: "服务暂不可用，请稍后重试",
}

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def error_code_for_status(status_code: int) -> str:
    """状态码 → 对外错误码；未登记的状态码退回通用 HTTP_ERROR。"""
    return ERROR_CODES.get(status_code, "HTTP_ERROR")


def status_message_for(status_code: int) -> str:
    """状态码 → 缺省人类可读文案。"""
    return STATUS_MESSAGES.get(status_code, "请求处理失败")


class AppError(Exception):
    """带机器码与人类文案的业务异常；由 ``install_error_handlers`` 统一渲染。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        msg: str,
        *,
        details: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(msg)
        self.status_code = int(status_code)
        self.code = code
        self.msg = msg
        self.details = details
        self.headers = dict(headers or {})


def mask_exception_for_client(
    exc: BaseException | None,
    *,
    logger: Optional[Any] = None,
    context: str = "",
    message: str = SANITIZED_5XX_MSG,
) -> str:
    """把异常转成**可对外展示**的固定文案：全貌只入服务端日志，绝不回显消息/堆栈。

    P8 不变量的单一实现落点。``install_error_handlers`` 只能兜住「未捕获异常 →
    500 信封」这一条路；**SSE 帧与手写 JSONResponse 兜不住**（流已开、状态码已发），
    于是各站历史上各自写 ``str(e)`` / ``f"...{e}"``，把内部路径 / 上游响应体 /
    SQL 片段送到客户端（CodeQL ``py/stack-trace-exposure`` 根因）。本函数是人与
    静态分析工具都能识别的**脱敏边界点**：调用它即表示「异常在此终止，不外泄」。

    - ``exc`` 只为语义显式（表明哪个异常被吞掉），**不参与返回值**——任何从异常消息
      派生的字段都会重新打开泄漏面；
    - ``logger`` 给出则先把全貌（含 traceback）落服务端日志。内部用 f-string 而非
      ``%s`` 惰性格式化，以兼容 std logging 与 loguru 两类 logger；传 loguru 站点请
      自行在原地记录异常，此处只取固定文案；
    - ``message`` 可按业务语义覆盖（如上游不可达比「服务器内部错误」更准确）。
    """
    if logger is not None:
        logger.exception(f"client-facing error masked (context={context or '-'})")
    return message


def error_body(
    code: str,
    msg: str,
    request_id: str,
    details: Any = None,
) -> Dict[str, Any]:
    """构造统一错误响应体 {code, msg, request_id, details?}。"""
    body: Dict[str, Any] = {"code": code, "msg": msg, "request_id": request_id or ""}
    if details is not None:
        body["details"] = details
    return body


def stream_error_frame(
    code: str,
    msg: str,
    request_id: str,
    details: Any = None,
) -> Dict[str, Any]:
    """构造流式统一错误帧 {type, code, msg, request_id, details?}。

    纯 dict，不依赖 starlette；SSE 与 WebSocket 共用同一形状。
    """
    frame: Dict[str, Any] = {
        "type": "error",
        "code": code,
        "msg": msg,
        "request_id": request_id or "",
    }
    if details is not None:
        frame["details"] = details
    return frame


def _default_get_request_id() -> str:
    """缺省 request_id 来源：agent-core OTel 上下文（懒导入，避免硬依赖）。"""
    from agent_core.tracing import get_request_id

    return get_request_id()


def _ensure_request_id(request: Any, rid: Callable[[], str]) -> str:
    """优先用中间件写入的 request.state.request_id；没有则生成并回写上下文。"""
    request_id = ""
    state = getattr(request, "state", None)
    if state is not None:
        request_id = getattr(state, "request_id", "") or ""
    if not request_id:
        request_id = rid()
    if not request_id:
        from agent_core.tracing import generate_request_id, set_request_context

        request_id = generate_request_id()
        set_request_context(request_id=request_id)
    if state is not None and not getattr(state, "request_id", ""):
        # 回写 request_id 是尽力而为：拿到只读 / 带 __slots__ 的 state 替身时只能放弃。
        # 射程收在 ``AttributeError``（而不是 Exception + pass）：除此之外这里没东西会坏，
        # 把别的异常吞掉就是把一个真 bug 读成“只是没写上”（S110 / BLE001 两条都在管这一形）。
        with contextlib.suppress(AttributeError):
            state.request_id = request_id
    return request_id


def _text_of(detail: Any) -> str:
    if isinstance(detail, str):
        return detail.strip()
    if isinstance(detail, dict):
        for key in ("msg", "message", "detail"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _normalize_detail(detail: Any, status_code: int) -> tuple[str, str, Any]:
    """把历史 ``detail`` 形状归一到 (code, msg, details?)。"""
    code = error_code_for_status(status_code)
    msg = status_message_for(status_code)
    details: Any = None

    if isinstance(detail, str):
        text = detail.strip()
        if text:
            if _CODE_RE.match(text):
                code = text
            else:
                msg = text
    elif isinstance(detail, dict):
        found_code = detail.get("code")
        if isinstance(found_code, str) and found_code.strip():
            code = found_code.strip()
        text = _text_of(detail)
        if text:
            msg = text
        extra = {
            key: value
            for key, value in detail.items()
            if key not in {"code", "message", "msg", "detail", "request_id"}
        }
        if extra:
            details = extra
    elif detail is not None and not isinstance(detail, (list, tuple)):
        details = detail

    if status_code >= 500:
        msg = SANITIZED_5XX_MSG
    return code, msg, details


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[Dict[str, Any]]:
    """校验错误脱敏：保留 loc/msg，丢弃 input 等可能回显原值的字段。"""
    sanitized: list[Dict[str, Any]] = []
    for raw in errors or []:
        if not isinstance(raw, dict):
            continue
        loc_raw = raw.get("loc") or []
        loc = [str(part) for part in loc_raw if isinstance(part, (str, int))]
        msg = raw.get("msg")
        if not isinstance(msg, str) or not msg.strip():
            msg = "校验失败"
        sanitized.append({"loc": loc, "msg": msg.strip()})
    return sanitized


def _validation_message(errors: Sequence[Any]) -> str:
    """校验错误的对外文案：能用 guardrails.auth 的人话格式化就用，回退到状态码默认句。

    只接 ``ImportError``：本节面在 ``agent_core.guardrails.auth``，它不在位（拆包 / 循环导入
    未解）才是该回退的形状；``format_validation_error`` 自己抛出的异常必须往上送（由
    未捕获通路变成 500），拿 ``except Exception`` 接住就等于“格式化器坏了，但对外看上去像
    用户写错了字段”——那是把实现缺陷洗成入参问题。
    """
    try:
        from agent_core.guardrails.auth import format_validation_error

        return format_validation_error(list(errors))
    except ImportError:
        return status_message_for(422)


def make_error_response(
    status_code: int,
    code: str,
    msg: str,
    request_id: str,
    headers: Optional[Dict[str, str]] = None,
    details: Any = None,
) -> Any:
    """构造统一错误 JSONResponse（自动带 X-Trace-Id 头）。需 starlette（``web`` extra）。"""
    from starlette.responses import JSONResponse

    resp_headers = dict(headers or {})
    if request_id and "X-Trace-Id" not in resp_headers:
        resp_headers["X-Trace-Id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, msg, request_id, details),
        headers=resp_headers,
    )


def install_error_handlers(
    app: Any,
    *,
    get_request_id: Optional[Callable[[], str]] = None,
    logger: Optional[Any] = None,
    sanitize_5xx_msg: str = SANITIZED_5XX_MSG,
    normalize_http_errors: bool = False,
) -> Any:
    """注册统一错误 handler。

    **两条通路各自独立，注册 ``AppError`` 不受 ``normalize_http_errors`` 管**：

    - ``AppError`` handler 始终注册。它是**新增出口**（存量代码零处 ``raise AppError``），
      装上即不改变任何现存请求的响应体；新代码要拿统一信封，抛 ``AppError`` 就够了，
      不需要本开关。
    - ``normalize_http_errors=False``（**默认**）：其余三类（``StarletteHTTPException`` /
      ``RequestValidationError`` / 未捕获 ``Exception``）保持历史行为 —— 4xx/422 仍走
      FastAPI 原生 ``{detail}``。在册决定 D-2=A 钉的就是这一格，用例是
      ``test_http_exception_4xx_detail_unchanged``；把它翻成默认 True 属**存量对外形状变更**，
      须逐 app 显式开启，见 docs/plans/plan-error-contract-staged-split-2026-11-06.md §4。
    - ``normalize_http_errors=True``（最终态，**须调用方显式传**）：同时接管上述三类，
      4xx 保留业务状态码与文案。
    - ``get_request_id`` / ``logger`` 注入：解耦各应用日志与 trace 实现；
      缺省分别用 ``agent_core.tracing.get_request_id`` 与 ``agent_core.logging``。
    - 优先读中间件写入的 ``request.state.request_id``（与 401/429/400 共用同一 trace），
      无中间件时生成并回写 OTel 上下文。
    """
    rid = get_request_id or _default_get_request_id
    log = logger or get_logger("agent_core.guardrails.errors")

    async def app_error_handler(request: Any, exc: AppError) -> Any:
        request_id = _ensure_request_id(request, rid)
        # 脱敏的射程是「未捕获异常的消息/堆栈」，不是「服务端自己声明的文案」。
        # ``AppError.msg`` 是代码里的常量（如「登录未启用：签名密钥未在位」），把它按
        # 状态码一起抹成通用句，抹掉的恰好是把「部署被改坏」和「用户输错」分开的唯一线索
        # —— 真含内部信息的东西本就不该写进 msg。所以 msg 一律保留。
        # ``details`` 反过来仍按状态码收：结构化上下文外泄风险高于文案，且当前零调用点
        # 依赖它，5xx 一律不带出（要放宽须另开批并逐条说明装什么）。
        msg = exc.msg
        details = None if exc.status_code >= 500 else exc.details
        return make_error_response(
            exc.status_code,
            exc.code,
            msg,
            request_id,
            headers=exc.headers,
            details=details,
        )

    async def unhandled_exception_handler(request: Any, exc: Exception) -> Any:
        request_id = _ensure_request_id(request, rid)
        log.exception("Unhandled exception %s %s", request.method, request.url.path)
        return make_error_response(500, "INTERNAL_ERROR", sanitize_5xx_msg, request_id)

    app.add_exception_handler(AppError, app_error_handler)

    if normalize_http_errors:
        from fastapi.exceptions import RequestValidationError
        from starlette.exceptions import HTTPException as StarletteHTTPException

        async def http_exception_handler(request: Any, exc: StarletteHTTPException) -> Any:
            request_id = _ensure_request_id(request, rid)
            if exc.status_code < 400:
                from fastapi.exception_handlers import http_exception_handler as default_handler

                return await default_handler(request, exc)
            code, msg, details = _normalize_detail(exc.detail, exc.status_code)
            return make_error_response(
                exc.status_code,
                code,
                msg,
                request_id,
                headers=dict(exc.headers or {}),
                details=details,
            )

        async def validation_exception_handler(request: Any, exc: RequestValidationError) -> Any:
            request_id = _ensure_request_id(request, rid)
            errors = exc.errors()
            return make_error_response(
                422,
                "VALIDATION_ERROR",
                _validation_message(errors),
                request_id,
                details=_sanitize_validation_errors(errors),
            )

        app.add_exception_handler(StarletteHTTPException, http_exception_handler)
        app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


__all__ = [
    "SANITIZED_5XX_MSG",
    "ERROR_CODES",
    "STATUS_MESSAGES",
    "AppError",
    "error_code_for_status",
    "status_message_for",
    "error_body",
    "stream_error_frame",
    "mask_exception_for_client",
    "make_error_response",
    "install_error_handlers",
]
