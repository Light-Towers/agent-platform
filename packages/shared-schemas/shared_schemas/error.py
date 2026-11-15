"""统一错误响应契约（最终态：``{code, msg, request_id, details?}``）。

所有服务在返回非 2xx 响应时，应使用 ``ErrorEnvelope``（与
``agent_core.guardrails.errors`` 的 HTTP / 流式错误帧同形）：
- ``code`` 机器可读错误码，客户端据此分支；
- ``msg`` 已脱敏的人类可读文案，直接展示给用户；
- ``request_id`` 链路排查 ID；
- ``details`` 可选结构化上下文（校验错误 ``loc/msg`` 列表、健康检查明细等）。

``ErrorResponse`` 是 P1-2 的旧 ``{detail, code?, request_id?}`` 形状，仅为兼容
保留；新代码不得再使用，也不得把 ``ErrorResponse.to_dict()`` 塞进
``HTTPException.detail``（会双层嵌套成 ``{"detail": {"detail": ...}}``）。

用法示例::

    from shared_schemas import ErrorEnvelope
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content=ErrorEnvelope(
            code="BUDGET_EXCEEDED",
            msg="请求额度已耗尽",
            request_id=request_id,
        ).to_dict(),
    )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    """最终态统一错误响应体。"""

    code: str = Field(..., description="机器可读错误码（如 BUDGET_EXCEEDED / VALIDATION_ERROR）")
    msg: str = Field(..., description="已脱敏的人类可读错误描述")
    request_id: str = Field(..., description="请求追踪 ID（链路排查用）")
    details: Any | None = Field(None, description="可选结构化上下文（不得含敏感原文）")

    def to_dict(self) -> dict:
        """序列化为 dict；省略 ``details=None``。"""
        d: dict = {"code": self.code, "msg": self.msg, "request_id": self.request_id}
        if self.details is not None:
            d["details"] = self.details
        return d


class ErrorResponse(BaseModel):
    """旧 ``{detail, code?, request_id?}`` 形状；保留仅为兼容，新代码用 ``ErrorEnvelope``。"""

    detail: str = Field(..., description="人类可读错误描述（兼容 FastAPI 默认格式）")
    code: str | None = Field(None, description="机器可读错误码（如 BUDGET_EXCEEDED / NOT_FOUND）")
    request_id: str | None = Field(None, description="请求追踪 ID（链路排查用）")

    def to_dict(self) -> dict:
        """序列化为 dict（省略 None 字段，保持与 FastAPI 默认格式最大兼容）。"""
        d: dict = {"detail": self.detail}
        if self.code is not None:
            d["code"] = self.code
        if self.request_id is not None:
            d["request_id"] = self.request_id
        return d


__all__ = ["ErrorEnvelope", "ErrorResponse"]
