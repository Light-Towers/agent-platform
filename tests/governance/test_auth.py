"""auth.py 单元测试：鉴权与会话策略（B7b-4 主体化后的契约）。

覆盖三件事，缺一即回归：
1. **会话身份来自服务端断言主体，与凭据无关**（链① 已拆 ⇒ 不得再有任何形式回到密钥派生）；
2. **鉴权启用时忽略客户端 thread_id**（防劫持语义不变）；
3. **开发模式（未配置 API_KEY）仍信任客户端 thread_id**（本地多会话联调是对外承诺能力）。

签名级守门用 AST 扫两 app 的源文件（不 import 联邦包，避免 ``api`` 顶层包在本 session 被遮蔽）。
"""

import ast
import hashlib
from pathlib import Path

import pytest
from agent_core.guardrails.auth import DEV_THREAD_ID, THREAD_ID_PREFIX, resolve_thread_identity
from agent_runtime import workspace_registry as _wr
from agent_runtime.workspace_registry import bind_tenant_context, reset_tenant_context
from agent_server.api.auth import resolve_thread_id, verify_api_key
from agent_server.config import get_settings
from fastapi import HTTPException

_ROOT = Path(__file__).resolve().parents[2]


def _force_unbound_tenant():
    """把租户 ContextVar 显置为「未绑定」，返回 token 供 finally 复位。

    必要性：本 session 跑全量时，上一个用例若泄漏了绑定值，「部署级 default」这条
    分支就会读到假现值。直接写模块私有变量是破窗，但比把断言写成「或」弱判定诚实。
    """
    return _wr._tenant_id_ctx.set(_wr._TENANT_UNSET)


def _set_api_key(monkeypatch, key: str):
    monkeypatch.setenv("API_KEY", key)
    get_settings.cache_clear()


def test_verify_api_key_disabled_returns_none(monkeypatch):
    _set_api_key(monkeypatch, "")
    assert verify_api_key(None) is None
    assert verify_api_key("any") is None


def test_verify_api_key_enabled_correct(monkeypatch):
    _set_api_key(monkeypatch, "secret123")
    assert verify_api_key("secret123") == "secret123"


def test_verify_api_key_enabled_wrong_raises_401(monkeypatch):
    _set_api_key(monkeypatch, "secret123")
    with pytest.raises(HTTPException) as exc:
        verify_api_key("wrong")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        verify_api_key(None)
    assert exc.value.status_code == 401


def test_resolve_thread_id_disabled_trusts_client(monkeypatch):
    _set_api_key(monkeypatch, "")
    assert resolve_thread_id("client-tid") == "client-tid"
    assert resolve_thread_id(None) == DEV_THREAD_ID


def test_resolve_thread_id_enabled_uses_asserted_tenant(monkeypatch):
    """鉴权启用：主体取服务端断言租户，客户端伪造 session_id 不生效（防劫持）。"""
    _set_api_key(monkeypatch, "secret123")
    token = bind_tenant_context("acme")
    try:
        tid = resolve_thread_id("attacker-guess")
        assert tid == resolve_thread_identity("acme")
        assert tid == f"{THREAD_ID_PREFIX}acme"
        # 与凭据彻底脱钩：既不是旧的 48bit 裸哈希，也不是任何密钥派生值
        assert tid != f"user-{hashlib.sha256(b'secret123').hexdigest()[:12]}"
        assert tid != f"user-{hashlib.sha256(b'secret123').hexdigest()[:32]}"
        # 客户端值不参与（同一主体下不同 session_id 落同一桶）
        assert resolve_thread_id("another-guess") == tid
        assert resolve_thread_id(None) == tid
    finally:
        reset_tenant_context(token)


def test_resolve_thread_id_enabled_falls_back_to_deployment_default(monkeypatch):
    """ContextVar 未绑定 → 部署级 default_tenant_id（与 import/sql_router 同语义）。"""
    _set_api_key(monkeypatch, "secret123")
    monkeypatch.setenv("DEFAULT_TENANT_ID", "single-tenant-x")
    get_settings.cache_clear()
    token = _force_unbound_tenant()
    try:
        assert resolve_thread_id("client-tid") == resolve_thread_identity("single-tenant-x")
    finally:
        reset_tenant_context(token)


def test_resolve_thread_id_enabled_different_tenants_isolate(monkeypatch):
    """不同断言租户 ⇒ 不同会话桶（这是「主体化」相对「同密钥共用一桶」的细化方向）。"""
    _set_api_key(monkeypatch, "key-a")
    t_a = bind_tenant_context("tenant-a")
    try:
        tid_a = resolve_thread_id("x")
    finally:
        reset_tenant_context(t_a)

    t_b = bind_tenant_context("tenant-b")
    try:
        tid_b = resolve_thread_id("x")
    finally:
        reset_tenant_context(t_b)

    assert tid_a != tid_b


@pytest.mark.parametrize(
    "relative",
    [
        "applications/agent_server/api/auth.py",
        "applications/agent_federation/api/auth.py",
    ],
)
def test_resolve_thread_id_signature_has_no_credential_slot(relative):
    """签名级守门：两 app 的 ``resolve_thread_id`` 形参集恰为 ``{client_thread_id}``。

    与 B7b-2 同构的做法：留着凭据形参就是留着缺口，故在**类型层面**封死。
    用 AST 而非 ``inspect.signature`` —— 联邦 ``api`` 包在根 session 不可靠可导入。
    """
    tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8"))
    fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_thread_id"),
        None,
    )
    assert fn is not None, f"{relative} 内未找到 resolve_thread_id"
    args = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert set(args) == {"client_thread_id"}, f"{relative} 形参集越界：{args}"
    assert fn.args.posonlyargs == [] and fn.args.vararg is None and fn.args.kwarg is None
