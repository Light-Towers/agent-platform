"""优化 I：精确回忆单测（thread_id + checkpointer 回溯原文）。

不连真实 PG：mock 内核 AsyncPostgresSaver 的 alist_messages，验证
- 消息规整（role 归一化、content 提取、index 顺序）
- 关键词精确过滤（字面子串，非语义）
- limit 取末尾 N 条
- 无 checkpointer / 异常时安全返回 []
"""

import sys
from types import SimpleNamespace

import pytest


class _FakeMessage:
    def __init__(self, type_, content, id_=None, created_at=None):
        self.type = type_
        self.content = content
        self.id = id_
        self.additional_kwargs = {"created_at": created_at} if created_at else {}


class _FakeCheckpointer:
    def __init__(self, messages):
        self._messages = messages
        self.calls = []

    async def alist_messages(self, config):
        self.calls.append(config)
        return self._messages


def _make_cp():
    return _FakeCheckpointer([
        _FakeMessage("human", "你好，我是财务小张", "m0", "2026-08-10T09:00:00+00:00"),
        _FakeMessage("ai", "好的，已记录您是财务角色", "m1"),
        _FakeMessage("human", "帮我生成本月报表", "m2", "2026-08-10T09:05:00+00:00"),
        _FakeMessage("ai", "报表已生成，使用 X 模板", "m3"),
        _FakeMessage("tool", '{"status":"ok"}', "m4"),
    ])


async def test_get_thread_history_normalizes_roles():
    import app.memory.recall_exact as r

    items = await r.get_thread_history(_make_cp(), "t1")
    assert len(items) == 5
    assert items[0]["role"] == "user"        # human -> user
    assert items[1]["role"] == "assistant"   # ai -> assistant
    assert items[4]["role"] == "tool"
    assert items[0]["index"] == 0
    assert items[0]["content"] == "你好，我是财务小张"
    assert items[0]["created_at"] == "2026-08-10T09:00:00+00:00"


async def test_get_thread_history_keyword_filter():
    import app.memory.recall_exact as r

    items = await r.get_thread_history(_make_cp(), "t1", keyword="报表")
    # 仅含「报表」的两条命中
    assert len(items) == 2
    assert all("报表" in it["content"] for it in items)


async def test_get_thread_history_keyword_case_insensitive():
    import app.memory.recall_exact as r

    items = await r.get_thread_history(_make_cp(), "t1", keyword="X 模板")
    assert len(items) == 1
    assert items[0]["content"] == "报表已生成，使用 X 模板"


async def test_get_thread_history_limit_takes_tail():
    import app.memory.recall_exact as r

    items = await r.get_thread_history(_make_cp(), "t1", limit=2)
    assert [it["index"] for it in items] == [3, 4]


async def test_get_thread_history_no_checkpointer():
    import app.memory.recall_exact as r

    assert await r.get_thread_history(None, "t1") == []


async def test_get_thread_history_handles_exception():
    import app.memory.recall_exact as r

    class _Boom:
        async def alist_messages(self, config):
            raise RuntimeError("pg down")

    assert await r.get_thread_history(_Boom(), "t1") == []


async def test_search_in_thread_requires_keyword():
    import app.memory.recall_exact as r

    assert await r.search_in_thread(_make_cp(), "t1", "") == []


async def test_passes_thread_id_to_checkpointer():
    import app.memory.recall_exact as r

    cp = _make_cp()
    await r.get_thread_history(cp, "thread-xyz")
    assert cp.calls[-1] == {"configurable": {"thread_id": "thread-xyz"}}
