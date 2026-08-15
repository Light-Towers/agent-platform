"""SessionCoordinator 单元测试：验证 queue 策略互斥 + 唤醒。"""

import asyncio

import pytest

from app.infra.coordinator import SessionCoordinator


@pytest.mark.asyncio
async def test_serialize_first_request():
    """首个请求直接获取执行权。"""
    coord = SessionCoordinator(policy="queue", enabled=True)
    decision = await coord.acquire("s1", "r1")
    assert decision.decision_type == "serialize"
    await coord.release("s1", "r1")


@pytest.mark.asyncio
async def test_reject_policy():
    """reject 策略：会话忙碌时拒绝新请求。"""
    coord = SessionCoordinator(policy="reject", enabled=True)
    await coord.acquire("s1", "r1")
    decision = await coord.acquire("s1", "r2")
    assert decision.decision_type == "reject"
    await coord.release("s1", "r1")


@pytest.mark.asyncio
async def test_queue_policy_serializes():
    """queue 策略：第二个请求等待第一个释放后执行。"""
    coord = SessionCoordinator(policy="queue", enabled=True)
    await coord.acquire("s1", "r1")
    decision2 = await coord.acquire("s1", "r2")
    assert decision2.decision_type == "queue"

    order: list[str] = []

    async def r2_work():
        await coord.wait_for_turn("s1", "r2")
        order.append("r2")
        await coord.release("s1", "r2")

    task = asyncio.create_task(r2_work())
    await asyncio.sleep(0.01)
    order.append("r1")
    await coord.release("s1", "r1")
    await task
    assert order == ["r1", "r2"]


@pytest.mark.asyncio
async def test_queue_multiple_serialized():
    """queue 策略：多个请求按 FIFO 顺序执行。"""
    coord = SessionCoordinator(policy="queue", enabled=True)
    await coord.acquire("s", "a")

    order: list[str] = []

    async def worker(rid: str):
        d = await coord.acquire("s", rid)
        if d.decision_type == "queue":
            await coord.wait_for_turn("s", rid)
        order.append(rid)
        await coord.release("s", rid)

    tasks = [asyncio.create_task(worker(rid)) for rid in ("b", "c", "d")]
    await asyncio.sleep(0.02)
    order.append("a")
    await coord.release("s", "a")
    await asyncio.gather(*tasks)
    assert order == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_different_sessions_concurrent():
    """异 session 不阻塞。"""
    coord = SessionCoordinator(policy="queue", enabled=True)
    d1 = await coord.acquire("s1", "r1")
    d2 = await coord.acquire("s2", "r2")
    assert d1.decision_type == "serialize"
    assert d2.decision_type == "serialize"
    await coord.release("s1", "r1")
    await coord.release("s2", "r2")


@pytest.mark.asyncio
async def test_disabled_passthrough():
    """禁用时直通 serialize。"""
    coord = SessionCoordinator(policy="queue", enabled=False)
    d = await coord.acquire("s1", "r1")
    assert d.decision_type == "serialize"
    await coord.release("s1", "r1")
    await coord.wait_for_turn("s1", "r1")
