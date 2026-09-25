"""统一错误响应信封（P1-2 契约收敛）。

所有服务在返回非 2xx 响应时，应使用本模型（或至少兼容其字段）：
- FastAPI 默认 ``{"detail": "..."}`` 是本模型 ``detail`` 字段的子集，向后兼容。
- 新增可选 ``code``（机器可读错误码）和 ``request_id``（链路排查）不破坏现有客户端。

用法示例::

    from shared_schemas import ErrorResponse
    from fastapi.responses import JSONResponse

    raise HTTPException(
        status_code=429,
        detail=ErrorResponse(code="BUDGET_EXCEEDED", detail="请求额度已耗尽").to_dict(),
    )
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """统一错误响应信封。兼容 FastAPI 默认 ``{"detail": ...}`` 格式。"""

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


__all__ = ["ErrorResponse"]
