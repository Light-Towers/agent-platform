"""C2 统一信封契约模型。

来源：跨项目接口契约 v1.1 §C2。
成功响应强制带 readiness + classification + sources；
知识类响应必带 citations；数值类响应必须能追溯到 sources。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Readiness(str, Enum):
    """数据就绪度（INV-3 / §7）。"""

    READY = "READY"
    PARTIAL = "PARTIAL"
    SYNTHETIC = "SYNTHETIC"
    NOT_CONNECTED = "NOT_CONNECTED"


class DataClassification(str, Enum):
    """数据分级（F02 / §17.2，五级）。"""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    PII = "PII"
    FINANCIAL = "FINANCIAL"


class EgressDecision(str, Enum):
    """出域决策（Model Router 消费，§17.5）。"""

    ALLOW = "ALLOW"
    DENY = "DENY"
    MASKED = "MASKED"


class Source(BaseModel):
    """数据来源（数值类响应必须能追溯到 sources）。"""

    type: str = Field(description="table | api | knowledge")
    name: str
    as_of: str | None = Field(None, description="数据时点")


class Citation(BaseModel):
    """知识引用（无 citation 的答案平台侧拒绝展示）。"""

    knowledge_id: str
    chunk_id: str | None = None
    scope: str | None = None


class SkillRequest(BaseModel):
    """C2 请求信封。"""

    request_id: str
    skill: str
    params: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class SkillSuccessEnvelope(BaseModel):
    """C2 成功响应信封（强制 readiness + classification + sources）。

    缺 readiness 的数值响应 → 客户端判 fail（不是 warn）。
    SYNTHETIC / PARTIAL 必须同时写入 warnings。
    """

    request_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    readiness: Readiness
    classification: DataClassification
    sources: list[Source] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SkillErrorEnvelope(BaseModel):
    """C2 错误响应信封。"""

    request_id: str
    error: dict[str, Any] = Field(description="含 code / message / retryable")
