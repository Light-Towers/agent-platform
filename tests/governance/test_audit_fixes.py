"""审计修复回归测试：覆盖 v2 代码级审计中真实成立的 P0/P1/P2 问题。

对应审计条目：
  #一 #二  → app/api/routes.py 统一 _cleanup（见 test_query_lifecycle.py）
  #三      → admission 超时把 DB 行标 rejected，不再伪装 completed
  #四      → SessionCoordinator cancel 协议，避免排队死请求卡死会话
  #六      → CircuitBreaker HALF_OPEN 限制并发探测数
  #十一    → embedding 生产护栏（EMBEDDING_REQUIRE_REAL）
  #十二    → L1 chitchat 弱礼貌词改为整句匹配，避免业务句误路由
"""


import pytest
from agent_core.intent.classifier import classify_l1
from agent_core.resilience import CircuitBreaker
from agent_runtime.coordinator import SessionCoordinator

# ---------------------------------------------------------------------------
# #四：coordinator cancel 协议
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coordinator_cancel_skips_dead_pending_request():
    """A 执行中，B 排队，B 客户端断开（cancel），A release 应 promote C 而非死 B。"""
    coord = SessionCoordinator(policy="queue", enabled=True)
    sid = "s1"

    # A 获取执行权
    d_a = await coord.acquire(sid, "A")
    assert d_a.decision_type == "serialize"
    assert coord._active.get(sid) == "A"

    # B、C 排队
    d_b = await coord.acquire(sid, "B")
    d_c = await coord.acquire(sid, "C")
    assert d_b.decision_type == "queue"
    assert d_c.decision_type == "queue"

    # B 断开 → cancel
    await coord.cancel(sid, "B")

    # A 释放：应跳过已取消的 B，promote C
    await coord.release(sid, "A")
    assert coord._active.get(sid) == "C"
    assert "B" not in coord._cancelled or coord._active.get(sid) != "B"


@pytest.mark.asyncio
async def test_coordinator_cancel_idempotent_and_noop_for_active():
    """cancel 对已 active 请求是 no-op（active 由 release 释放）。"""
    coord = SessionCoordinator(policy="queue", enabled=True)
    sid = "s2"
    await coord.acquire(sid, "X")
    # cancel 一个 active 请求不应把它从 active 移除
    await coord.cancel(sid, "X")
    assert coord._active.get(sid) == "X"
    # 再 release 正常清理
    await coord.release(sid, "X")
    assert coord._active.get(sid) is None


# ---------------------------------------------------------------------------
# #六：CircuitBreaker HALF_OPEN 并发探测限制
# ---------------------------------------------------------------------------

def test_half_open_limits_concurrent_probes():
    """OPEN→HALF_OPEN 后，只允许 max_half_open_probe 个并发 probe，其余被拒绝。"""
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01, max_half_open_probe=1)

    # 制造 OPEN
    assert cb.allow() is True
    cb.record_failure()  # 1 次失败 → OPEN
    assert cb.allow() is False  # 冷却中

    # 冷却结束 → HALF_OPEN
    cb._opened_at = -1e9
    assert cb.allow() is True  # 第 1 个 probe 放行
    # 第 2 个并发 probe 在 max=1 时应被拒绝（视为仍 OPEN）
    assert cb.allow() is False

    # 第 1 个 probe 成功 → 回 CLOSED，inflight 归零
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb._half_open_inflight == 0


def test_half_open_allows_n_probes_when_max_greater_than_one():
    """max_half_open_probe>1 时允许 N 个并发 probe。"""
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01, max_half_open_probe=3)
    cb.record_failure()
    cb._opened_at = -1e9
    assert cb.allow() is True
    assert cb.allow() is True
    assert cb.allow() is True
    assert cb.allow() is False  # 第 4 个被拒


# ---------------------------------------------------------------------------
# #十二：L1 chitchat 弱礼貌词整句匹配
# ---------------------------------------------------------------------------

def test_chitchat_weak_keyword_not_matching_business_query():
    """含礼貌词的业务问题不应被误判为 CHITCHAT（如'谢谢你帮我分析合同'）。"""
    r = classify_l1("谢谢你帮我分析一下这份合同")
    assert r.primary.value != "chitchat"


def test_chitchat_weak_keyword_pure_greeting_matches():
    """纯问候/礼貌语（整句等于弱词）仍判 CHITCHAT。"""
    r = classify_l1("谢谢")
    assert r.primary.value == "chitchat"
    r2 = classify_l1("hi")
    assert r2.primary.value == "chitchat"


def test_chitchat_strong_keyword_still_shortcuts():
    """强意图词 substring 仍短路为 CHITCHAT。"""
    r = classify_l1("你是谁")
    assert r.primary.value == "chitchat"


# ---------------------------------------------------------------------------
# #十一：embedding 生产护栏
# ---------------------------------------------------------------------------

def test_embed_require_real_rejects_mock(monkeypatch):
    """EMBEDDING_REQUIRE_REAL=true 且底层退化为 Mock 时，embed_texts 必须抛错。"""
    from unittest.mock import AsyncMock, MagicMock

    from agent_core.memory.embedder import MockEmbedder
    from agent_server.rag import embed as embed_mod

    monkeypatch.setenv("EMBEDDING_REQUIRE_REAL", "true")

    # 模拟内核返回 MockEmbedder（spec 让它通过 isinstance 检查）
    mock_provider = MagicMock(spec=MockEmbedder)
    mock_provider.aembed = AsyncMock(return_value=[[0.1] * 8])
    monkeypatch.setattr(embed_mod, "get_embedder", lambda force=False: mock_provider)

    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.run(embed_mod.embed_texts(["hi"]))


def test_embed_require_real_off_allows_mock(monkeypatch):
    """默认（护栏关闭）允许 Mock，保持测试/CI 兼容。"""
    from unittest.mock import AsyncMock, MagicMock

    from agent_core.memory.embedder import MockEmbedder
    from agent_server.rag import embed as embed_mod

    monkeypatch.setenv("EMBEDDING_REQUIRE_REAL", "false")

    mock_provider = MagicMock(spec=MockEmbedder)
    mock_provider.aembed = AsyncMock(return_value=[[0.1] * 8])
    monkeypatch.setattr(embed_mod, "get_embedder", lambda force=False: mock_provider)

    import asyncio

    out = asyncio.run(embed_mod.embed_texts(["hi"]))
    assert out == [[0.1] * 8]
