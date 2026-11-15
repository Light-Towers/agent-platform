# -*- coding: utf-8 -*-
"""角色 → 能力（feature）的**单一解释位**（D3；ADR-0015 §2.6(a)）。

- claims 只带**角色码**，不带权限集；「这个角色能干什么」由本模块的常量表算出。
- 权限映射不入库（本轮）：``role → features`` 是代码常量，改它 = 发版（可审计、可 blame）。
  将来迁库是纯 expand：claims 形状不变、消费点不变（D3「放弃」列）。
- **全仓不得自写 ``if role == "admin"``**（ADR-0015 §2.6(a)）：任何「角色能不能做 X」的
  判定只准调 :func:`has_feature` / :func:`features_for_role`；1b 起由 lint 钉字面比较。

D9 兜底（缺 role / 未知 role → viewer）与 P8（API_KEY 无 claims → viewer）共用
:func:`resolve_features` **一个入口**（H6：兜底逻辑只住一个函数，两路不各写一份）。
兜底可见性双通道（D9 订正口径，评审 #6）：

1. WARNING 按 ``(tenant, user)`` **首次**记一条（per-process 去重）；
2. **可聚合计数** :func:`role_fallback_count` 每次 +1——R-1 的触发条件
   「计数 > 0 持续超一个 TTL」评的是它，不是 WARNING 条数（per-process 去重会让
   条数封顶 1，触发条件永不可评）。

枚举值域与消费点/反证的对应关系见方案 §4 表（docs/plans/
plan-roles-kb-datasource-console-2026-11-11.md）；本模块只持值域本体，不重复那张表。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型注解用；运行期不 import（本模块保持零依赖环）
    from agent_runtime.identity import TokenClaims

__all__ = [
    "ROLE_ADMIN",
    "ROLE_EDITOR",
    "ROLE_VIEWER",
    "ROLES",
    "FEATURES",
    "ROLE_FEATURES",
    "has_feature",
    "features_for_role",
    "effective_role",
    "resolve_features",
    "role_fallback_count",
]

logger = logging.getLogger(__name__)

# --- 角色码（D1：内置三角色，一人一角色）------------------------------------

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER)

# --- feature 枚举本体（§4；kb.config 随模板砍除移出，10→9）--------------------

FEATURES = frozenset({
    "chat.run",
    "session.history",
    "data.unmasked",
    "sql.train",
    "kb.upload",
    "kb.publish",
    "datasource.manage",
    "execution.control",
    "human_task.decide",
})

_VIEWER = frozenset({"chat.run", "session.history"})
_EDITOR = _VIEWER | {"kb.upload"}
_ADMIN = _EDITOR | {
    "data.unmasked",
    "sql.train",
    "kb.publish",
    "datasource.manage",
    "execution.control",
    "human_task.decide",
}

# 集合关系：admin ⊃ editor ⊃ viewer（§4）；键缺省即未知角色 ⇒ 空集。
ROLE_FEATURES: dict[str, frozenset[str]] = {
    ROLE_ADMIN: _ADMIN,
    ROLE_EDITOR: _EDITOR,
    ROLE_VIEWER: _VIEWER,
}

_EMPTY: frozenset[str] = frozenset()

# --- D9 兜底可见性（WARNING 首次去重 + 可聚合计数）---------------------------

_fallback_count = 0
_fallback_warned: set[tuple[str, str]] = set()


def _fallback_to_viewer(tenant: str, user: str) -> str:
    """记一次兜底并返回 viewer。WARNING 按 (tenant, user) 首次记一条；计数每次 +1。"""
    global _fallback_count
    _fallback_count += 1
    key = (tenant, user)
    if key not in _fallback_warned:
        _fallback_warned.add(key)
        logger.warning(
            "role 缺失/未知 ⇒ 按 viewer 兜底（最小权限，D9）：tenant=%r user=%r；"
            "累计第 %d 次——若持续出现请查签发方是否已带 role claim（升级窗口 ≤ 令牌 TTL）",
            tenant,
            user,
            _fallback_count,
        )
    return ROLE_VIEWER


def role_fallback_count() -> int:
    """D9 兜底累计次数（R-1 可评性：>0 持续超一个 TTL ⇒ 兜底在掩盖签发方问题）。"""
    return _fallback_count


# --- 查询面 -----------------------------------------------------------------

def features_for_role(role: str | None) -> frozenset[str]:
    """角色 → 能力集。未知角色/None → **空集**（fail-closed，不抛错）。"""
    return ROLE_FEATURES.get(role or "", _EMPTY)


def has_feature(
    role: str | None, code: str, *, tenant: str = "", user: str = ""
) -> bool:
    """「这个角色能不能做 X」的**唯一**判定入口（nl2sql 等子服务 import 它，D11/1c）。

    1c 统一两套兜底口径：值域收敛与 D9 可见性单一在 :func:`effective_role`，
    本函数把所有调用方（含子服务直调）收进同一条路径。此前直调会绕过
    ``effective_role`` 拿到空集、且不触发兜底计数（1a 遗留）；现在未知/缺失码
    一律按 viewer 收敛并计数，**不把 None 当 admin**。
    """
    return code in features_for_role(effective_role(role, tenant=tenant, user=user))


def effective_role(role: str | None, *, tenant: str = "", user: str = "") -> str:
    """值域收敛：合法码原样返回；缺失/未知 → viewer 兜底（带 D9 可见性副作用）。

    未知码（签发方拼错、跨版本新码）与缺失同桶：能力面取最小权限，且计数可见
    ——否则静默降级会掩盖签发方配置错（D9 代价，与 F9 同族风险的镜像面）。
    值域校验不放在 ``verify_token``：令牌有效性（签名/租户）与角色词汇表是两件事，
    混在一起会把「一个拼错的码」升级成「整条身份被拒」。
    """
    if role in ROLES:
        return role
    return _fallback_to_viewer(tenant, user)


def resolve_features(claims: TokenClaims | None) -> frozenset[str]:
    """**单一入口**（H6）：JWT 路径传 claims；API_KEY 路径（P8）传 None。

    不得在调用方再写第二份「无 role 怎么办」——两条路径的兜底口径由本函数一处兼现。
    """
    if claims is None:
        return features_for_role(_fallback_to_viewer("*", "*"))
    return features_for_role(
        effective_role(claims.role, tenant=claims.tenant_id, user=claims.user_id or "")
    )
