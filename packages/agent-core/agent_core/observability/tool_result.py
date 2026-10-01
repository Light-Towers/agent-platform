# -*- coding: utf-8 -*-
"""ToolResult 协议（stdlib 零依赖，方案 v3.1 定板：outcome 语义承载唯一方案）。

工具用 `ToolResult` 替代裸字符串返回，把「业务结果文本」与「观测语义」解耦：

- ``text``：LLM 可见文本——包装器把它作为工具返回值转发给 Agent 链路；
- ``outcome``：事件 outcome 维度（success/empty/exception/guarded/degraded/timeout）；
- ``detail``：机器可读补充（错误码上下文等，包装器上报前截断）；
- ``error_class``：异常类名或业务错误码（如 ``TableWhitelist``）。

工具体内 catch 分支**不再直调 monitor**（散点埋点），改为返回 ToolResult——
语义统一、可 lint 管辖、内核无 monitor 依赖。纯二态工具（成功/抛异常）
保持返回普通值/抛异常，包装器自动派生 success/exception。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["ToolOutcome", "ToolResult"]


class ToolOutcome(str, Enum):
    """tool_outcome 事件取值全集（与既有生产代码取值对齐，见方案 §2 基线）。"""

    SUCCESS = "success"
    EMPTY = "empty"
    EXCEPTION = "exception"
    GUARDED = "guarded"
    DEGRADED = "degraded"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ToolResult:
    """工具结构化返回值：outcome 语义 + LLM 文本一体。"""

    text: str
    outcome: ToolOutcome = ToolOutcome.SUCCESS
    detail: str = ""
    error_class: str | None = None

    def __str__(self) -> str:
        return self.text
