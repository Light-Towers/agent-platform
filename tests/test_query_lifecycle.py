"""Request lifecycle 回归测试：验证 P0 资源泄漏修复。

覆盖审计中两条最严重的泄漏路径：
  * coordinator reject 后必须释放 coordinator 槽位 + admission 容量
  * semantic cache hit 后必须释放 coordinator 槽位 + admission 容量

两者都必须在提前返回（raise / return StreamingResponse）之前经过统一
_cleanup()，否则同 session 后续请求会永久排队（capacity 泄漏）。

注意：通过 ASGITransport 直接驱动 app（不触发 lifespan 真实 DB 初始化），
手动注入 mock coordinator / admission_queue，并 patch 缓存相关函数。
"""

import httpx  # noqa: E402
import pytest  # noqa: E402

# 复用 app.main 的 app 实例（ASGITransport 不触发 lifespan，手动注入 mock state）
from agent_server.main import app as _app  # noqa: E402


class _Decision:
    def __init__(self, status="admitted", request_id=None, decision_type=None, reason=None):
        self.status = status
        self.request_id = request_id
        self.decision_type = decision_type
        self.reason = reason


class _MockCoordinator:
    def __init__(self, decision_type="admit"):
        self._decision_type = decision_type
        self.released = []
        self.acquired = []

    async def acquire(self, thread_id, request_id):
        self.acquired.append((thread_id, request_id))
        if self._decision_type == "reject":
            return _Decision(decision_type="reject", reason="full")
        return _Decision(decision_type="admit")

    async def release(self, thread_id, request_id):
        self.released.append((thread_id, request_id))


async def _async_embed():
    return [0.1] * 8


async def _async_cache_hit():
    return "cached-text"


class _MockAdmission:
    def __init__(self):
        self.completed = []
        self.enqueued = []

    async def enqueue(self, *args, **kwargs):
        rid = kwargs.get("request_id") or (args[0] if args else "r")
        self.enqueued.append(rid)
        return _Decision(status="admitted", request_id=rid)

    async def mark_completed(self, request_id):
        self.completed.append(request_id)


def _make_settings():
    """构造一个开启 coordination + admission 的 settings（admission 需 db_enabled）。"""
    from agent_server.config import Settings

    s = Settings()
    s.coordination_enabled = True
    s.admission_enabled = True
    s.database_url = "postgresql://fake/fake"  # 仅用于让 admission_effective_enabled=True
    return s


@pytest.fixture
def app_with_mocks(monkeypatch):
    app = _app
    # 重置可能因其他测试污染的 state
    settings = _make_settings()
    monkeypatch.setattr("agent_server.api.routes.get_settings", lambda: settings)

    coordinator = _MockCoordinator()
    admission = _MockAdmission()
    app.state.coordinator = coordinator
    app.state.admission_queue = admission
    # 这些路径不访问 graph / otel，留 None 即可
    app.state.graph = None
    app.state.otel_tracer = None

    yield app, coordinator, admission

    # 清理，避免影响其它用例
    for attr in ("coordinator", "admission_queue", "graph", "otel_tracer"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


async def _post_query(app, query="hi"):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/query", json={"query": query}) as resp:
            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk
            return resp.status_code, body


async def test_coordinator_reject_releases_resources(app_with_mocks, monkeypatch):
    """P0 #一：coordinator reject 后必须释放 coordinator + admission，否则容量泄漏。"""
    app, coordinator, admission = app_with_mocks
    coordinator._decision_type = "reject"

    status, _ = await _post_query(app, "hello")
    assert status == 409, f"reject 应返回 409，实际 {status}"

    # 关键断言：提前 raise 前必须经过 _cleanup()
    assert coordinator.released, "reject 后 coordinator.release 未被调用 → 槽位泄漏"
    assert admission.completed, "reject 后 admission.mark_completed 未被调用 → 容量泄漏"


async def test_cache_hit_releases_resources(app_with_mocks, monkeypatch):
    """P0 #二：semantic cache hit（正常路径）后必须释放 coordinator + admission。"""
    app, coordinator, admission = app_with_mocks
    coordinator._decision_type = "admit"

    # 让缓存查询命中：pool 非 None、embed_query 返回定长向量、cache_lookup 命中
    fake_pool = object()
    monkeypatch.setattr("agent_server.api.routes.get_pool", lambda: fake_pool)
    monkeypatch.setattr("agent_server.api.routes.embed_query", lambda q: _async_embed())
    monkeypatch.setattr(
        "agent_server.api.routes.semantic_cache.cache_lookup",
        lambda pool, emb, thr: _async_cache_hit(),
    )

    status, body = await _post_query(app, "repeat question")
    assert status == 200, f"cache hit 应返回 200，实际 {status}"
    assert b"cache_hit" in body, "响应应含 cache_hit 事件"

    # 关键断言：直接 return StreamingResponse 前必须经过 _cleanup()
    assert coordinator.released, "cache hit 后 coordinator.release 未被调用 → 槽位泄漏"
    assert admission.completed, "cache hit 后 admission.mark_completed 未被调用 → 容量泄漏"


async def test_cleanup_idempotent(app_with_mocks, monkeypatch):
    """_cleanup() 幂等：即使被多次调用也不重复释放 / 重复 mark_completed。"""
    app, coordinator, admission = app_with_mocks
    coordinator._decision_type = "reject"

    status, _ = await _post_query(app, "hello")
    assert status == 409
    # reject 路径：_cleanup 在 raise 前调用 1 次；_stream 的 finally 不会执行
    # （reject 在 _stream 外），故每资源恰好释放一次
    assert len(coordinator.released) == 1, coordinator.released
    assert len(admission.completed) == 1, admission.completed
