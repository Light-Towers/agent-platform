"""resolve_thread_id 会话解析策略测试（B7b-4 主体化后的契约，对齐 app/api/auth.py）。

**两个正交维度各自有用例**（方案 A-3 要求的双向锁）：
- 维度一「是否启用鉴权」决定信任谁：``API_KEY`` 为空 ⇒ 信任客户端（本地多会话联调）；
- 维度二「主体来源三态」只在鉴权启用时求值：断言租户 → ``SINGLE_TENANT`` → insecure 兜底。

覆盖：
- 鉴权启用：按服务端断言主体经内核 ``resolve_thread_identity`` 派生，忽略客户端 thread_id
  （防劫持 + 多个请求落到同一 thread，TB-14 语义不变；DUP-1 收敛后不再是凭据摘要）
- 鉴权启用 + 无任何断言：退 ``DEV_THREAD_ID``（单桶，与今天等价）；开启
  ``DEPLOY_ENFORCE_IDENTITY`` 则 fail-fast
- 开发模式（未配置 API_KEY）：信任客户端 thread_id，缺省 dev-default-thread
"""

import hashlib
import logging

import pytest
from agent_core.guardrails.auth import resolve_thread_identity

_IDENTITY_ENVS = (
    "SINGLE_TENANT",
    "TENANT_JWT_PUBLIC_KEYS_FILE",
    "DEPLOY_ENFORCE_IDENTITY",
)


@pytest.fixture(autouse=True)
def _isolated_identity(monkeypatch):
    """隔离主体来源的全部外部输入，并把联邦租户 ContextVar 显置为「未绑定」。

    「未绑定」必须显式设定：同 session 里前一个用例若绑定了租户，本用例会读到假现值，
    三态求值就测不到它宣称测的那条分支。
    """
    from api import context as ctx

    for var in _IDENTITY_ENVS:
        monkeypatch.delenv(var, raising=False)
    token = ctx._tenant_id_ctx.set(ctx._TENANT_UNBOUND)
    yield
    ctx._tenant_id_ctx.reset(token)


def _load_with_api_key(monkeypatch, value: str):
    """动态设置 api.auth.API_KEY，隔离环境变量副作用（不 reload，避免被 os.getenv 覆盖）。"""
    import api.auth as auth_mod

    monkeypatch.setattr(auth_mod, "API_KEY", value)
    return auth_mod


def test_auth_enabled_uses_asserted_tenant(monkeypatch):
    from api.context import reset_tenant_context, set_tenant_context

    auth = _load_with_api_key(monkeypatch, "secret-key")
    token = set_tenant_context("acme")
    try:
        t1 = auth.resolve_thread_id("client-supplied-1")
        t2 = auth.resolve_thread_id("client-supplied-2")
        # 鉴权启用：忽略客户端 thread_id，同一断言主体派生同一稳定会话
        assert t1 == t2 == resolve_thread_identity("acme")
        assert t1.startswith("tenant-")
        # 与凭据彻底脱钩（旧形态的两代都不得复现）
        assert t1 != "user-" + hashlib.sha256(b"secret-key").hexdigest()[:12]
        assert t1 != "user-" + hashlib.sha256(b"secret-key").hexdigest()[:32]
    finally:
        reset_tenant_context(token)


def test_auth_enabled_single_tenant_when_unbound(monkeypatch):
    """断言 ContextVar 未绑定 → 部署级 SINGLE_TENANT（三态第 2 态）。"""
    monkeypatch.setenv("SINGLE_TENANT", "acme-corp")
    auth = _load_with_api_key(monkeypatch, "secret-key")
    assert auth.resolve_thread_id("attacker-guess") == resolve_thread_identity("acme-corp")


def test_auth_enabled_insecure_falls_back_to_shared_thread(monkeypatch):
    """三态第 3 态（未开启强制）：退共享 DEV_THREAD_ID ⇒ 桶数与今天等价（仍是 1）。"""
    auth = _load_with_api_key(monkeypatch, "secret-key")
    assert auth.resolve_thread_id("a") == auth.resolve_thread_id("b") == "dev-default-thread"


def test_auth_enabled_insecure_enforce_fails_fast(monkeypatch):
    """三态第 3 态 + DEPLOY_ENFORCE_IDENTITY=true ⇒ fail-fast，绝不静默落共享桶。"""
    monkeypatch.setenv("DEPLOY_ENFORCE_IDENTITY", "true")
    auth = _load_with_api_key(monkeypatch, "secret-key")
    with pytest.raises(auth.PrincipalUndetermined):
        auth.resolve_thread_id("whatever")


def test_auth_enabled_ignores_client_thread_id(monkeypatch):
    from api.context import reset_tenant_context, set_tenant_context

    auth = _load_with_api_key(monkeypatch, "k")
    token = set_tenant_context("tenant-k")
    try:
        assert auth.resolve_thread_id("attacker-guess") == auth.resolve_thread_id(None)
    finally:
        reset_tenant_context(token)


def test_auth_enabled_different_tenants_derive_different_sessions(monkeypatch):
    from api.context import reset_tenant_context, set_tenant_context

    auth = _load_with_api_key(monkeypatch, "key-a")
    ta = set_tenant_context("tenant-a")
    try:
        tid_a = auth.resolve_thread_id(None)
    finally:
        reset_tenant_context(ta)
    tb = set_tenant_context("tenant-b")
    try:
        tid_b = auth.resolve_thread_id(None)
    finally:
        reset_tenant_context(tb)
    assert tid_a != tid_b


def test_dev_mode_trusts_client_thread_id(monkeypatch):
    auth = _load_with_api_key(monkeypatch, "")
    assert auth.resolve_thread_id("my-session") == "my-session"


def test_dev_mode_keeps_multi_session_capability(monkeypatch):
    """维度一优先：即使处于 insecure（无公钥/无 SINGLE_TENANT），开发态仍按客户端值分会话。

    这是「两维被误合并」的专用回归用例 —— 若实现把 insecure 无条件退 DEV_THREAD_ID，
    本地多轮联调会被静默砍掉。
    """
    auth = _load_with_api_key(monkeypatch, "")
    assert auth.resolve_thread_id("session-1") != auth.resolve_thread_id("session-2")


def test_dev_mode_defaults_when_missing(monkeypatch):
    auth = _load_with_api_key(monkeypatch, "")
    assert auth.resolve_thread_id(None) == "dev-default-thread"


def test_insecure_shared_thread_warns_once(monkeypatch, caplog):
    """退回共享桶属「能跑但不安全」的中间态：首次告警一次，不刷屏也不静默。"""
    auth = _load_with_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(auth, "_insecure_warned", False)
    with caplog.at_level(logging.WARNING):
        auth.resolve_thread_id("a")
        auth.resolve_thread_id("b")
    hits = [r for r in caplog.records if "无法断言主体" in r.getMessage()]
    assert len(hits) == 1
