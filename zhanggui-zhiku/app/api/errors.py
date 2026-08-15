# -*- coding: utf-8 -*-
"""
统一错误响应 / 异常处理器（M5，方案 §9）。

对外错误响应统一 ``{code, msg, request_id}``，``msg`` 不含堆栈 / 内部路径 / 密钥；
内部异常详情保留在服务端日志（logging），返回给用户的为脱敏文案。

本模块依赖 fastapi/starlette（仅 web 运行时加载）；纯逻辑见
``app/utils/error_response_utils.py`` 与 ``app/utils/security_guard_utils.py``。
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logger import logger
from app.core.tracing import get_request_id
from app.utils.error_response_utils import error_body, error_code_for_status
from app.utils.security_guard_utils import format_validation_error

_SANITIZED_5XX_MSG = "服务器内部错误，请稍后重试"


def request_id_of(request: Request) -> str:
    """读取当前请求的 request_id：优先 middleware 写入的 request.state，其次 OTel 上下文。"""
    return getattr(request.state, "request_id", "") or get_request_id()


def error_response(
    status_code: int,
    code: str,
    msg: str,
    request_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """构造统一错误 JSONResponse（自动带 X-Trace-Id 头，方案 §8.3）。"""
    resp_headers = dict(headers or {})
    if request_id and "X-Trace-Id" not in resp_headers:
        resp_headers["X-Trace-Id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, msg, request_id),
        headers=resp_headers,
    )


def _sanitize_detail(detail: Any, status_code: int) -> str:
    """脱敏：5xx 一律通用文案；4xx 仅当 detail 为安全字符串时透传。"""
    if status_code >= 500:
        return _SANITIZED_5XX_MSG
    if isinstance(detail, str) and detail:
        return detail
    return "请求处理失败"


def _log_http_error(request: Request, status_code: int, detail: Any) -> None:
    """内部日志保留完整详情（含异常细节），仅供服务端排查。"""
    logger.error("HTTP %s %s -> %s detail=%s", request.method, request.url.path, status_code, detail)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException（含路由抛出的 4xx/5xx）→ 统一 {code, msg, request_id}。"""
    request_id = request_id_of(request)
    status_code = exc.status_code
    _log_http_error(request, status_code, exc.detail)
    return error_response(
        status_code,
        error_code_for_status(status_code),
        _sanitize_detail(exc.detail, status_code),
        request_id,
        headers=dict(exc.headers or {}),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """pydantic 校验失败（如 query 超长）→ 400 + 可读文案（含当前长度/上限）。"""
    request_id = request_id_of(request)
    logger.warning("Validation error %s %s: %s", request.method, request.url.path, exc.errors())
    return error_response(400, "VALIDATION_ERROR", format_validation_error(exc.errors()), request_id)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常 → 500 脱敏文案（详情仅入服务端日志，不泄露堆栈/内部路径）。"""
    request_id = request_id_of(request)
    logger.exception("Unhandled exception %s %s", request.method, request.url.path)
    return error_response(500, "INTERNAL_ERROR", _SANITIZED_5XX_MSG, request_id)


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理器（M5，方案 §9 错误脱敏）。"""
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
