"""resolve_thread_id 会话解析策略测试（对齐 app/api/auth.py）。

覆盖：
- 认证启用：按 API_KEY 哈希派生稳定会话，忽略客户端 thread_id（防劫持 + 跨请求续接，修复 TB-14）
- 开发模式（未配置 API_KEY）：信任客户端 thread_id，缺省 dev-default-thread
"""


def _load_with_api_key(monkeypatch, value: str):
    """动态设置 api.auth.API_KEY，隔离环境变量副作用（不 reload，避免被 os.getenv 覆盖）。"""
    import api.auth as auth_mod

    monkeypatch.setattr(auth_mod, "API_KEY", value)
    return auth_mod


def test_auth_enabled_derives_stable_session_from_key(monkeypatch):
    auth = _load_with_api_key(monkeypatch, "secret-key")
    t1 = auth.resolve_thread_id("client-supplied-1", api_key="secret-key")
    t2 = auth.resolve_thread_id("client-supplied-2", api_key="secret-key")
    # 认证启用：忽略客户端 thread_id，同一 key 派生同一稳定会话
    assert t1 == t2
    assert t1.startswith("user-")
    assert len(t1) == len("user-") + 12


def test_auth_enabled_ignores_client_thread_id(monkeypatch):
    auth = _load_with_api_key(monkeypatch, "k")
    assert auth.resolve_thread_id("attacker-guess", api_key="k") == auth.resolve_thread_id(None, api_key="k")


def test_auth_enabled_different_keys_derive_different_sessions(monkeypatch):
    a = _load_with_api_key(monkeypatch, "key-a")
    b = _load_with_api_key(monkeypatch, "key-b")
    ta = a.resolve_thread_id(None, api_key="key-a")
    tb = b.resolve_thread_id(None, api_key="key-b")
    assert ta != tb


def test_dev_mode_trusts_client_thread_id(monkeypatch):
    auth = _load_with_api_key(monkeypatch, "")
    assert auth.resolve_thread_id("my-session", api_key=None) == "my-session"


def test_dev_mode_defaults_when_missing(monkeypatch):
    auth = _load_with_api_key(monkeypatch, "")
    assert auth.resolve_thread_id(None, api_key=None) == "dev-default-thread"
