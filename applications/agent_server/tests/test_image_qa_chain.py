# -*- coding: utf-8 -*-
"""会话传图完整链路回归（fake pool）：save → get → 租户拒绝 → data URI → 多模态合成。

防回归：pool API 用错（acquire vs connection）、ref 租户绕过、VL content 形状退化——
这些在单测里 mock 掉整函数时抓不到，这里用薄 fake pool 走真调用链（plan-image-qa-fullstack）。
"""

from __future__ import annotations

import base64

from agent_server import chat_images as store
from agent_server.api import query_router as qr
from agent_server.planners.deterministic import DeterministicPlanner

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wFbC+8AAAAASUVORK5CYII="
)


class _Conn:
    def __init__(self, mem: dict):
        self.mem = mem

    async def execute(self, sql, *args):
        if sql.strip().startswith("INSERT"):
            ref, tenant, session, content, ctype, size = args
            self.mem[ref] = (bytes(content), ctype)

    async def fetchrow(self, sql, *args):
        ref, tenant = args
        value = self.mem.get(ref)
        return {"content": value[0], "content_type": value[1]} if value else None

    async def fetchval(self, *args):
        return 0


class _CM:
    def __init__(self, mem):
        self.mem = mem

    async def __aenter__(self):
        return _Conn(self.mem)

    async def __aexit__(self, *args):
        return False


class _Pool:
    """只实现 psycopg3 AsyncConnectionPool 的 connection()（无 acquire）。"""

    def __init__(self, mem):
        self.mem = mem

    def connection(self):
        return _CM(self.mem)


class _StubLLM:
    def __init__(self):
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return type("R", (), {"content": "ok"})()


async def test_image_qa_full_chain(monkeypatch):
    mem: dict = {}
    monkeypatch.setattr(store, "get_pool", lambda: _Pool(mem))

    ref = store.make_ref("default", "s1", "png")
    await store.save_image(ref, "default", "s1", _TINY_PNG, "image/png")
    assert ref in mem, "save 失败（pool API 可能退回 acquire）"

    got = await store.get_image(ref, "default")
    assert got is not None and got[0] == _TINY_PNG
    assert await store.get_image(ref, "evil") is None, "跨租户必须拒绝"

    images = await qr._resolve_images({"images": [ref]}, "default")
    assert len(images) == 1 and images[0].startswith("data:image/png;base64,")

    vl, text = _StubLLM(), _StubLLM()
    await DeterministicPlanner()._compose("这张图是什么", [], [], text, images=images, vl_llm=vl)
    assert len(vl.calls) == 1 and len(text.calls) == 0
    assert any(block.get("type") == "image_url" for block in vl.calls[0][1]["content"])
