"""子 Agent 调用记录 schema（网关侧路由追踪）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubagentCall(BaseModel):
    """子 Agent 调用请求记录。"""

    subagent_name: str = Field(..., description="子 Agent 名称")
    args: dict[str, Any] = Field(default_factory=dict, description="调用参数")
    mode: str = Field("remote", description="调用模式：remote（Agent Protocol）/ local（fallback）")


class SubagentResult(BaseModel):
    """子 Agent 调用结果。"""

    subagent_name: str = Field(..., description="子 Agent 名称")
    result: str = Field(..., description="子 Agent 返回文本")
    success: bool = Field(True, description="是否成功")
    latency_ms: float | None = Field(None, description="调用延迟（毫秒）")
    fallback: bool = Field(False, description="是否走了本地 fallback")
    error: str | None = Field(None, description="错误信息（success=False 时）")
