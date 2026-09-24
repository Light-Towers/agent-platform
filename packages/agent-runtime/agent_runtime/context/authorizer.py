"""ContextAuthorizer（Context Governance）：Memory 级权限过滤。

Skill 级已有权限过滤，但 Memory 级没有——跨租户/跨用户的 Memory 可能被错误召回。
本模块在召回后、组装前做一次权限校验，确保只把当前请求有权访问的 Memory 送进 LLM。

策略：
- **tenant 隔离**：Memory 的 tenant_id 必须匹配请求的 tenant_id（或 Memory 是共享的）；
- **user 隔离**：Memory 的 user_id 必须匹配请求的 user_id（或 Memory 是 shared 级别）；
- **workspace 隔离**：Memory 的 workspace_id 必须匹配（或共享）。

Memory 的可见性级别（metadata.visibility）：
- ``private``：仅创建者可见（tenant + user 都必须匹配）；
- ``tenant``：同租户可见（tenant 匹配即可）；
- ``shared``：全局共享（不做隔离）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuthorizationDecision:
    """单条 Memory 的授权决策。"""

    memory_index: int
    allowed: bool
    reason: str = ""


@dataclass
class AuthorizationReport:
    """授权报告。"""

    decisions: list[AuthorizationDecision] = field(default_factory=list)
    allowed_count: int = 0
    denied_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [
                {
                    "memory_index": d.memory_index,
                    "allowed": d.allowed,
                    "reason": d.reason,
                }
                for d in self.decisions
            ],
            "allowed_count": self.allowed_count,
            "denied_count": self.denied_count,
        }


class ContextAuthorizer:
    """Memory 级权限过滤：租户/用户/工作空间隔离。

    用法::

        authorizer = ContextAuthorizer()
        report = authorizer.authorize(memories, tenant_id="t1", user_id="u1")
        filtered = authorizer.apply(memories, report)
    """

    def __init__(
        self,
        *,
        visibility_key: str = "visibility",
        tenant_key: str = "tenant_id",
        user_key: str = "user_id",
        workspace_key: str = "workspace_id",
    ) -> None:
        self.visibility_key = visibility_key
        self.tenant_key = tenant_key
        self.user_key = user_key
        self.workspace_key = workspace_key

    def authorize(
        self,
        memories: list[Any],
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorizationReport:
        """校验一批 Memory 的访问权限，返回 AuthorizationReport。"""
        report = AuthorizationReport()

        for idx, mem in enumerate(memories):
            meta = _get_metadata(mem)
            decision = self._check_one(
                idx,
                meta,
                tenant_id=tenant_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            report.decisions.append(decision)
            if decision.allowed:
                report.allowed_count += 1
            else:
                report.denied_count += 1

        return report

    def apply(
        self,
        memories: list[Any],
        report: AuthorizationReport,
    ) -> list[Any]:
        """根据授权报告过滤 Memory 列表。"""
        allowed_indices = {
            d.memory_index for d in report.decisions if d.allowed
        }
        return [mem for idx, mem in enumerate(memories) if idx in allowed_indices]

    def _check_one(
        self,
        idx: int,
        meta: dict[str, Any],
        *,
        tenant_id: str | None,
        user_id: str | None,
        workspace_id: str | None,
    ) -> AuthorizationDecision:
        visibility = str(meta.get(self.visibility_key, "tenant")).lower()

        # shared：全局共享，不做隔离
        if visibility == "shared":
            return AuthorizationDecision(idx, True, "shared visibility")

        # private：仅创建者可见
        if visibility == "private":
            mem_tenant = meta.get(self.tenant_key)
            mem_user = meta.get(self.user_key)
            if tenant_id is not None and mem_tenant != tenant_id:
                return AuthorizationDecision(
                    idx, False, f"private: tenant mismatch ({mem_tenant!r} != {tenant_id!r})"
                )
            if user_id is not None and mem_user != user_id:
                return AuthorizationDecision(
                    idx, False, f"private: user mismatch ({mem_user!r} != {user_id!r})"
                )
            return AuthorizationDecision(idx, True, "private: owner matched")

        # tenant（默认）：同租户可见
        mem_tenant = meta.get(self.tenant_key)
        if tenant_id is not None and mem_tenant is not None and mem_tenant != tenant_id:
            return AuthorizationDecision(
                idx, False, f"tenant: mismatch ({mem_tenant!r} != {tenant_id!r})"
            )

        # workspace 隔离（可选：workspace_id 匹配或 Memory 无 workspace 限定）
        mem_workspace = meta.get(self.workspace_key)
        if (
            workspace_id is not None
            and mem_workspace is not None
            and mem_workspace != workspace_id
        ):
            return AuthorizationDecision(
                idx, False, f"workspace: mismatch ({mem_workspace!r} != {workspace_id!r})"
            )

        return AuthorizationDecision(idx, True, "tenant: matched")


def _get_metadata(mem: Any) -> dict[str, Any]:
    """从 MemoryRecallResult 或 dict 提取 metadata。"""
    if hasattr(mem, "metadata"):
        return dict(mem.metadata or {})
    if isinstance(mem, dict):
        return dict(mem.get("metadata", {}))
    return {}
