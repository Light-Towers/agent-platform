"""会话标识解析（对齐 app/api/auth.py 已验证策略）。

B7b-4：会话身份不再从调用方凭据派生（拆 CodeQL ``py/weak-sensitive-data-hashing`` 链①）。
**两个维度正交，不得合并成一条链**：

- **维度一「是否启用鉴权」决定信任谁**：``API_KEY`` 为空（``DISABLE_AUTH=true`` 开发态）
  ⇒ 一律信任客户端 ``thread_id``，缺省 ``DEV_THREAD_ID``，方便本地多轮联调 —— 此分支
  **逐字维持现状**，下面的三态完全不参与。``API_KEY`` 非空 ⇒ 忽略客户端值（防劫持），
  进入维度二。
- **维度二「主体来源三态」只在鉴权启用时求值**，顺序固定：
  1. ``get_asserted_tenant_context()`` 非空（``identity_bridge`` 已验签绑定的断言值）→ 用它；
  2. 否则 ``resolve_startup_tenant_mode()`` 返回 ``("single", tenant)`` → 用 ``tenant``；
  3. 否则（``jwt`` 模式但未带令牌 / ``insecure``）：``DEPLOY_ENFORCE_IDENTITY=true`` → 抛
     :class:`PrincipalUndetermined`（调用方兜 401，不外泄细节）；未开启 → 返回
     ``DEV_THREAD_ID`` 并**首次告警一次**。

等价性（必须写破，免得误读为「砍掉了 dev 多会话」）：第 3 态退 ``DEV_THREAD_ID`` **不影响**
维度一的开发态多会话能力（那条能力活在 ``API_KEY`` 为空分支）；与今天「同一把密钥的所有
客户端共用一个 ``user-<digest>`` 桶」相比**桶数不变（仍是 1）**，变的只是 id 形态。反过来，
若把两个维度误合并（``insecure`` 时无条件退 ``DEV_THREAD_ID`` 而不先查维度一），才会静默
砍掉本地联调能力 —— 该方向由 ``tests`` 双向用例锁住。

DUP-1/DUP-3 收敛：派生实现在 agent_core（``resolve_thread_identity``，主体明文、不做摘要）；
旧格式落盘会话的一次性迁移见 scripts/migrate_thread_identity.py（枚举式，不再复算密钥）。
"""

import os
import threading

from agent_core.guardrails.auth import DEV_THREAD_ID, resolve_thread_identity
from agent_core.logging import get_logger
from agent_runtime.identity import env_bool, resolve_startup_tenant_mode

from api.context import get_asserted_tenant_context

logger = get_logger(__name__)

API_KEY = os.getenv("API_KEY", "")

_insecure_warned = False
_insecure_warn_lock = threading.Lock()


class PrincipalUndetermined(ValueError):
    """鉴权已启用但服务端无法断言主体（``DEPLOY_ENFORCE_IDENTITY=true`` 下的 fail-fast）。

    继承 ``ValueError`` 以保留「入参/配置非法即 ValueError」的既有契约，同时让调用方能把它
    与内核 ``resolve_thread_identity`` 的**字符集配置错误**区分开：后者是部署配置问题
    （500 语义），不该伪装成 401 认证失败。
    """


def _warn_insecure_once() -> None:
    """无主体可断言而退回共享会话：首次告警一次（与 ``require_identity_startup_guard`` 同构）。"""
    global _insecure_warned
    if _insecure_warned:
        return
    with _insecure_warn_lock:
        if not _insecure_warned:
            _insecure_warned = True
            logger.warning(
                "[auth] 鉴权已启用但服务端无法断言主体（未配置验签公钥/SINGLE_TENANT，且未开启 "
                "DEPLOY_ENFORCE_IDENTITY）：会话退回共享 %r。生产部署请配置 RS256 验签公钥或显式 "
                "SINGLE_TENANT=<tenant>，否则不同客户端的会话将落在同一桶。",
                DEV_THREAD_ID,
            )


def resolve_principal() -> str | None:
    """维度二：解析服务端**已断言**的会话主体（当前口径 = 租户，Q1=(a)）。

    :return: 断言主体；三态第 3 态且未开启强制身份时为 ``None``（调用方退共享会话）
    :raises PrincipalUndetermined: 三态第 3 态且 ``DEPLOY_ENFORCE_IDENTITY=true``
    """
    asserted = get_asserted_tenant_context()
    if asserted:
        return asserted
    mode, tenant = resolve_startup_tenant_mode()
    if mode == "single" and tenant:
        return tenant
    if env_bool("DEPLOY_ENFORCE_IDENTITY", False):
        raise PrincipalUndetermined(
            f"鉴权已启用但主体无法断言（mode={mode}、ContextVar 未绑定）："
            "DEPLOY_ENFORCE_IDENTITY=true 要求 fail-fast，见 docs/adr/0007-server-asserted-tenant-identity.md §4.1"
        )
    _warn_insecure_once()
    return None


def resolve_thread_id(client_thread_id: str | None) -> str:
    """解析本次请求应使用的 thread_id（**签名里没有凭据位**，凭据在类型层面进不来）。

    Args:
        client_thread_id: 客户端在请求体/路径里传入的会话标识（鉴权启用时被忽略）。

    Raises:
        PrincipalUndetermined: 鉴权启用、主体不可断言且开启了 ``DEPLOY_ENFORCE_IDENTITY``。
        ValueError: 断言主体字符集非法（内核 ``resolve_thread_identity`` 的 fail-fast）。
    """
    if not API_KEY:
        # 维度一：开发态信任客户端（多会话本地联调是对外承诺能力）
        return client_thread_id or DEV_THREAD_ID
    # 维度二：鉴权启用 ⇒ 主体由服务端断言，绝不使用客户端值与凭据
    principal = resolve_principal()
    if principal is None:
        return DEV_THREAD_ID
    return resolve_thread_identity(principal)
