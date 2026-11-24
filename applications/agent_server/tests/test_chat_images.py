# -*- coding: utf-8 -*-
"""会话图片存储/上传测试：ref 形状、租户隔离、格式白名单（plan-image-qa-fullstack §刀3）。"""

from agent_server.chat_images import delete_expired, ext_for_content_type, get_image, make_ref, save_image


class _FakeCursor:
    rowcount = 0

    async def fetchone(self):
        return None


class _FakeConn:
    """psycopg3 签名：execute(sql, (params,)) → cursor；无 fetchrow/fetchval。"""

    async def execute(self, sql, params=None):
        assert "%s" in sql and "$1" not in sql
        assert isinstance(params, tuple)
        return _FakeCursor()


class _FakePool:
    """只实现 psycopg3 AsyncConnectionPool 的 connection()；若代码用 acquire() 会当场 AttributeError。"""

    def connection(self):
        return _AsyncCM()


class _AsyncCM:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *a):
        return False


class TestPoolApi:
    async def test_save_uses_connection(self, monkeypatch):
        monkeypatch.setattr("agent_server.chat_images.get_pool", lambda: _FakePool())
        await save_image("ref", "t", "s", b"x", "image/png")  # 不抛即证明用了 connection()

    async def test_get_uses_connection(self, monkeypatch):
        monkeypatch.setattr("agent_server.chat_images.get_pool", lambda: _FakePool())
        assert await get_image("chat-images/t/s/x.png", "t") is None

    async def test_delete_expired_uses_connection(self, monkeypatch):
        monkeypatch.setattr("agent_server.chat_images.get_pool", lambda: _FakePool())
        assert await delete_expired() == 0


class TestRef:
    def test_ref_contains_tenant_and_no_host(self):
        ref = make_ref("tenantA", "sess-1", "png")
        assert ref.startswith("chat-images/tenantA/sess-1/")
        assert "minio" not in ref and ":" not in ref.replace("chat-images", "")

    def test_refs_unique(self):
        assert make_ref("t", "s", "png") != make_ref("t", "s", "png")


class TestContentType:
    def test_allowed(self):
        assert ext_for_content_type("image/png") == "png"
        assert ext_for_content_type("image/jpeg") == "jpg"
        assert ext_for_content_type("image/webp") == "webp"
        assert ext_for_content_type("image/gif") == "gif"

    def test_with_charset(self):
        assert ext_for_content_type("image/png; charset=binary") == "png"

    def test_rejected(self):
        assert ext_for_content_type("text/html") is None
        assert ext_for_content_type("application/pdf") is None
        assert ext_for_content_type("image/svg+xml") is None  # SVG 带脚本风险，拒
