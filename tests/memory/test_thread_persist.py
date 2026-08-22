"""app/memory/thread_persist：Planner 路径对话历史读/写测试（Phase 3c）。

用 InMemorySaver 验证：append_thread 写回后可被 read_thread_messages 读回、
多轮累积顺序正确、空 answer / 无 checkpointer 为空操作（不阻塞主链路）。
"""

from __future__ import annotations

import pytest
from agent_server.memory import thread_persist


@pytest.fixture
def saver():
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@pytest.mark.asyncio
async def test_read_empty_history(saver):
    assert await thread_persist.read_thread_messages(saver, "t1") == []


@pytest.mark.asyncio
async def test_append_and_read_back(saver):
    await thread_persist.append_thread(saver, "t1", "你好", "你好！")
    msgs = await thread_persist.read_thread_messages(saver, "t1")
    assert len(msgs) == 2
    assert msgs[0].type == "human"
    assert msgs[0].content == "你好"
    assert msgs[1].type == "ai"
    assert msgs[1].content == "你好！"


@pytest.mark.asyncio
async def test_append_multiple_rounds_ordered(saver):
    await thread_persist.append_thread(saver, "t1", "q1", "a1")
    await thread_persist.append_thread(saver, "t1", "q2", "a2")
    msgs = await thread_persist.read_thread_messages(saver, "t1")
    assert [m.content for m in msgs] == ["q1", "a1", "q2", "a2"]


@pytest.mark.asyncio
async def test_append_empty_answer_noop(saver):
    await thread_persist.append_thread(saver, "t1", "q", "")
    assert await thread_persist.read_thread_messages(saver, "t1") == []


@pytest.mark.asyncio
async def test_threads_isolated(saver):
    await thread_persist.append_thread(saver, "t1", "q", "a")
    assert await thread_persist.read_thread_messages(saver, "t2") == []


@pytest.mark.asyncio
async def test_no_checkpointer_noop():
    assert await thread_persist.read_thread_messages(None, "t1") == []
    await thread_persist.append_thread(None, "t1", "q", "a")  # 不抛错


# ---------- WS-2：task_snapshot 通道读写 ----------


@pytest.mark.asyncio
async def test_snapshot_roundtrip(saver):
    snap = {"task": {"goal": "g", "completed_steps": ["s1"], "pending": [], "constraints": {}},
            "execution": {"outputs": {"search": "ok"}, "errors": {}, "skill_stack": []}}
    await thread_persist.append_thread(saver, "t1", "q", "a", snapshot=snap)
    got = await thread_persist.read_thread_snapshot(saver, "t1")
    assert got == snap
    # 消息通道不受影响
    assert len(await thread_persist.read_thread_messages(saver, "t1")) == 2


@pytest.mark.asyncio
async def test_snapshot_overwrite_latest_round(saver):
    await thread_persist.append_thread(saver, "t1", "q1", "a1", snapshot={"task": {"goal": "旧"}})
    await thread_persist.append_thread(saver, "t1", "q2", "a2", snapshot={"task": {"goal": "新"}})
    got = await thread_persist.read_thread_snapshot(saver, "t1")
    assert got["task"]["goal"] == "新"


@pytest.mark.asyncio
async def test_snapshot_absent_returns_none(saver):
    # 无历史 / 无快照写入 / 无 checkpointer 均为 None
    assert await thread_persist.read_thread_snapshot(saver, "t-empty") is None
    await thread_persist.append_thread(saver, "t1", "q", "a")  # 不带 snapshot
    assert await thread_persist.read_thread_snapshot(saver, "t1") is None
    assert await thread_persist.read_thread_snapshot(None, "t1") is None


@pytest.mark.asyncio
async def test_snapshot_threads_isolated(saver):
    await thread_persist.append_thread(saver, "t1", "q", "a", snapshot={"task": {"goal": "g1"}})
    assert await thread_persist.read_thread_snapshot(saver, "t2") is None
