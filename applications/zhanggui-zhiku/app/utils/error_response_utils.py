# -*- coding: utf-8 -*-
"""
统一错误响应格式（M5，方案 §9）。

对外错误响应统一为 ``{code, msg, request_id}``；``msg`` 不含堆栈 / 内部路径 / 密钥，
内部异常详情仅保留在服务端日志。

本模块为**纯逻辑**（不依赖 fastapi/starlette），便于无 web 依赖的单元测试直接验证；
``JSONResponse`` 包装与异常处理器见 ``app/api/errors.py``。
"""

from typing import Any, Dict

# 状态码 → 机器可读错误码（对外稳定，便于客户端程序化处理；不泄露内部细节）
ERROR_CODES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    422: "UNPROCESSABLE_ENTITY",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def error_code_for_status(status_code: int) -> str:
    """状态码 → 对外错误码；未登记的状态码退回通用 HTTP_ERROR。"""
    return ERROR_CODES.get(status_code, "HTTP_ERROR")


def error_body(code: str, msg: str, request_id: str) -> Dict[str, Any]:
    """构造统一错误响应体 {code, msg, request_id}。"""
    return {"code": code, "msg": msg, "request_id": request_id or ""}
