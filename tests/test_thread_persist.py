"""app/memory/thread_persist：Planner 路径对话历史读/写测试（Phase 3c）。

用 InMemorySaver 验证：append_thread 写回后可被 read_thread_messages 读回、
多轮累积顺序正确、空 answer / 无 checkpointer 为空操作（不阻塞主链路）。
"""

from __future__ import annotations

import pytest

from app.memory import thread_persist


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
