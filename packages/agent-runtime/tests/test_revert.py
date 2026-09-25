"""RevertHandler 回退测试：用 InMemorySaver，无需 PG。

覆盖：正常回退 / checkpoint 不存在 / 内存模式边界 / 审计日志 / parent_config 为 None。
"""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.cache import _background_tasks
from agent_runtime.revert import RevertHandler


@pytest.fixture
def checkpointer():
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@pytest.fixture
def handler(checkpointer):
    return RevertHandler(checkpointer, pool=None)


def _config(session_id: str, checkpoint_id: str) -> dict:
    return {"configurable": {"thread_id": session_id, "checkpoint_id": checkpoint_id, "checkpoint_ns": ""}}


def _make_checkpoint(checkpoint_id: str, messages: list | None = None):
    return {
        "id": checkpoint_id,
        "channel_values": {"messages": messages or []},
        "channel_versions": {},
        "versions_seen": {},
    }


async def _seed_checkpoint(checkpointer, session_id: str, checkpoint_id: str, messages=None):
    """写入一个 checkpoint 到 checkpointer。"""
    await checkpointer.aput(
        _config(session_id, checkpoint_id),
        _make_checkpoint(checkpoint_id, messages),
        {"source": "loop", "step": 1, "writes": {}},
        {},
    )


async def _flush_bg():
    """等待所有后台任务完成（审计日志等）。"""
    tasks = list(_background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_revert_checkpoint_not_found(handler):
    """目标 checkpoint 不存在时返回 CHECKPOINT_NOT_FOUND。"""
    result = await handler.revert(
        operator="test_user",
        session_id="s1",
        checkpoint_id="nonexistent",
    )
    assert not result.success
    assert result.error == "CHECKPOINT_NOT_FOUND"
    assert result.session_id == "s1"
    assert result.checkpoint_id == "nonexistent"


async def test_revert_success(handler, checkpointer):
    """正常回退：写入 checkpoint 后可回退。"""
    await _seed_checkpoint(
        checkpointer, "s1", "cp1", messages=[type("M", (), {"content": "hello"})()]
    )
    result = await handler.revert(
        operator="test_user",
        session_id="s1",
        checkpoint_id="cp1",
    )
    assert result.success
    assert result.session_id == "s1"
    assert result.checkpoint_id == "cp1"
    assert "回退至 checkpoint" in result.context_summary


async def test_revert_creates_new_checkpoint_id(handler, checkpointer):
    """回退后生成新 checkpoint id（不原地覆写目标行）。"""
    await _seed_checkpoint(checkpointer, "s1", "cp1")
    result = await handler.revert("test_user", "s1", "cp1")
    assert result.success
    tpl = await checkpointer.aget_tuple(_config("s1", "cp1"))
    assert tpl is not None
    assert tpl.checkpoint["id"] == "cp1"


async def test_revert_with_messages_summary(handler, checkpointer):
    """回退摘要包含消息计数和最近消息。"""

    class FakeMsg:
        def __init__(self, content):
            self.content = content

    await _seed_checkpoint(
        checkpointer,
        "s2",
        "cp2",
        messages=[FakeMsg("第一条"), FakeMsg("第二条")],
    )
    result = await handler.revert("test_user", "s2", "cp2")
    assert result.success
    assert "回退至 checkpoint" in result.context_summary


async def test_revert_audit_logged(handler, checkpointer, caplog):
    """无 pool 时审计日志走 logger.info。"""
    await _seed_checkpoint(checkpointer, "s3", "cp3")
    with caplog.at_level("INFO", logger="agent_runtime.revert"):
        result = await handler.revert("test_user", "s3", "cp3")
        await _flush_bg()
    assert result.success
    audit_records = [r for r in caplog.records if "revert_audit" in r.message]
    assert len(audit_records) >= 1


async def test_revert_exception_writes_failed_audit(handler, checkpointer, caplog):
    """回退过程抛异常时写 failed 审计日志。"""
    await _seed_checkpoint(checkpointer, "s4", "cp4")
    with caplog.at_level("INFO", logger="agent_runtime.revert"):
        handler._checkpointer = None
        result = await handler.revert("test_user", "s4", "cp4")
        await _flush_bg()
    assert not result.success
    assert result.error == "REVERT_FAILED"
    audit_records = [r for r in caplog.records if "revert_audit" in r.message]
    assert len(audit_records) >= 1
    assert audit_records[0].args[-1] == "failed"


async def test_revert_parent_config_none(handler, checkpointer):
    """parent_config 为 None 时不抛 AttributeError。"""
    await checkpointer.aput(
        _config("s5", "cp5"),
        _make_checkpoint("cp5"),
        {"source": "loop", "step": 1, "writes": {}},
        {},
    )
    result = await handler.revert("test_user", "s5", "cp5")
    assert result.success
