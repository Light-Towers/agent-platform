"""C2' 契约模型（v1.2：直接 REST，平台侧自组装 SkillResult）。

来源：跨项目接口契约 v1.2 §C2（修订自 v1.1 统一信封）。
v1.2 不再要求 warehouse 返回统一信封；exhibition-agent 直接调 warehouse REST 端点，
平台侧根据 REST JSON 自组装 SkillResult（readiness 从 data_readiness.level 映射、
classification 默认 INTERNAL、sources 从端点路径推导）。

保留的枚举与模型（平台侧自组装用）：
- Readiness / DataClassification / EgressDecision：枚举
- Source / Citation：结构模型

已移除（v1.1 信封，不再需要）：
- SkillRequest / SkillSuccessEnvelope / SkillErrorEnvelope
"""

from __future__ import annotations

from enum import Enum

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
    """数据来源（平台侧自组装，从端点路径推导）。"""

    type: str = Field(description="table | api | knowledge")
    name: str
    as_of: str | None = Field(None, description="数据时点")


class Citation(BaseModel):
    """知识引用（无 citation 的答案平台侧拒绝展示）。"""

    knowledge_id: str
    chunk_id: str | None = None
    scope: str | None = None
