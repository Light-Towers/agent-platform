"""C1 ExecutionContext 契约模型（字段冻结）。

来源：跨项目接口契约 v1.1 §C1 + 主方案 §2.2.1。
这是 INV-8 的真正载体：每次调用都携带一个不可伪造的上下文，
warehouse 侧只信 ExecutionContext，拒绝调用方自报 tenant。

字段已冻结，新增字段属 major 版本变更（契约 §2）。
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class TenantType(str, Enum):
    """租户类型（主方案 §4.4）。"""

    SPONSOR = "SPONSOR"
    VENUE = "VENUE"
    CONTRACTOR = "CONTRACTOR"
    EXHIBITOR = "EXHIBITOR"


class AuthSource(str, Enum):
    """上下文签发方。"""

    IAM = "IAM"
    SSO = "SSO"
    PLATFORM_LOCAL = "PLATFORM_LOCAL"


class ExecutionContext(BaseModel):
    """Trusted ExecutionContext（由 Foundation 签发，沿调用链传递）。

    字段冻结于契约 v1.1 §C1：
    - user_id / tenant_id / tenant_type / roles[] / scopes[] / auth_source / request_id
    - request_id 贯穿 Agent → Skill → Retrieval → Domain API → 审计
    """

    user_id: Annotated[str, Field(min_length=1, description="用户标识")]
    tenant_id: Annotated[str, Field(min_length=1, description="租户标识")]
    tenant_type: TenantType
    roles: list[str] = Field(default_factory=list, description="角色列表")
    scopes: list[str] = Field(
        default_factory=list,
        description="scope 列表，如 exhibition:{id} / venue:{id}",
    )
    auth_source: AuthSource
    request_id: Annotated[str, Field(min_length=1, description="审计键，贯穿全链路")]

    @field_validator("roles", "scopes")
    @classmethod
    def _no_none_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item or not isinstance(item, str):
                raise ValueError("roles/scopes 元素必须为非空字符串")
        return v
