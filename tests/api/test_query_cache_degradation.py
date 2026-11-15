"""嵌入器故障时语义缓存的降级形状（agent_server 读写两点，2026-10-27）。

**缺陷原状**：读路径把 `embed_query()` 与 `cache_backend.get()` 放在同一个 try 里，
嵌入器一抛异常，异常被吞后 `q_embedding` 停在 None，而写侧条件当时是
`final_answer and q_embedding is not None` ⇒ 嵌入器故障期间：

- L1 精确命中与负缓存检查**整块被跳过**（这两者本来都不需要向量）；
- 缓存一个键都不写，恢复之后仍是全冷缓存，而 `/health` 照旧报 ready。

这正是 ADR-0013 §2.3 记过的「装了但没接上」+ AGENTS.md 观测硬规矩 1「状态灯亮 ≠ 数据到」
的合流形状。修法依据在后端契约：`valkey_backend._resolve_embedding(embedding=None, …)`
会自行派生，失败则只跳过 L2；`_write_positive` 里 `pipe.set(keys["l1"], …)` 无条件执行、
L2 的 hset 才受 `vector is not None` 约束（均实读确认，不是设计意图推断）。

**同时守住成本性质**：happy path 仍只调用一次 embedder 并把同一向量同时喂给读写两点，
不是"改成让后端各算一遍"。
"""

from __future__ import annotations

import json

import pytest
from agent_server.main import app
from fastapi.testclient import TestClient


class _RecordingCache:
    """只记录跨边界参数的替身：命中与否由用例给定，不断言后端内部行为（那归契约用例）。"""

    enabled = True

    def __init__(self, hit=None) -> None:
        self._hit = hit
        self.get_calls: list[dict] = []
        self.set_calls: list[dict] = []

    async def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return self._hit

    async def set(self, **kwargs):
        self.set_calls.append(kwargs)


def types_contain(events: list[dict], kind: str) -> bool:
    return any(e.get("type") == kind for e in events)


def _events(resp) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in resp.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def cache(monkeypatch):
    """把工厂换成记录型后端；返回可改写的 holder，便于用例会后取读数。"""

    holder: dict[str, _RecordingCache] = {}

    def _install(hit=None):
        fake = _RecordingCache(hit=hit)
        holder["cache"] = fake
        monkeypatch.setattr("agent_server.api.query_router.get_cache", lambda scope: fake)
        return fake

    holder["install"] = _install
    yield holder


async def _raising_embed(_text):
    raise RuntimeError("embedder unreachable")


async def _ok_embed(_text):
    return [0.5] * 8


def _patch_embed(monkeypatch, fn):
    monkeypatch.setattr("agent_server.api.query_router.embed_query", fn)


def test_embedder_failure_still_consults_l1_and_still_writes(cache, monkeypatch):
    """嵌入器挂了：L1 查询照做（embedding=None 交给后端派生），写侧照写（退成只写 L1）。"""
    fake = cache["install"]()
    _patch_embed(monkeypatch, _raising_embed)

    with TestClient(app) as client:
        resp = client.post("/query", json={"query": "帮我写一首诗"})

    assert resp.status_code == 200, "缓存是优化不是正确性依赖：嵌入器故障不许改变响应码"
    assert types_contain(_events(resp), "done"), "流路必须正常收尾"
    assert fake.get_calls, "嵌入器失败不得连带跳过 get()——L1 精确命中与负缓存都不需要向量"
    assert fake.get_calls[0]["embedding"] is None, "读侧应把 None 交给后端自行派生/降级"
    assert fake.set_calls, "写侧不许把『嵌入器可用』当写入前提，否则恢复后缓存永远冷"
    assert fake.set_calls[0]["embedding"] is None


def test_happy_path_keeps_single_embedder_call_shared_by_read_and_write(cache, monkeypatch):
    """成本性质守门：可用时仍只算一次向量，且读写两点共用同一个值。"""
    calls: list[str] = []

    async def _counting_embed(text):
        calls.append(text)
        return [0.25] * 8

    fake = cache["install"]()
    monkeypatch.setattr("agent_server.api.query_router.embed_query", _counting_embed)

    with TestClient(app) as client:
        resp = client.post("/query", json={"query": "介绍一下这个项目"})

    assert resp.status_code == 200
    assert len(calls) == 1, f"单请求 embedding 调用必须 =1，实为 {len(calls)}"
    assert fake.get_calls and fake.set_calls
    assert fake.get_calls[0]["embedding"] == fake.set_calls[0]["embedding"] == [0.25] * 8


def test_cache_hit_short_circuit_survives_the_read_path_restructure(cache, monkeypatch):
    """读路径拆成两个 try 后，命中旁路必须仍然是"直接返回、不执行、不写回"。"""
    from agent_core.cache import CacheHit

    fake = cache["install"](hit=CacheHit(value={"answer": "cached-text"}, layer="l1"))
    _patch_embed(monkeypatch, _ok_embed)

    with TestClient(app) as client:
        resp = client.post("/query", json={"query": "重复的问题"})

    events = _events(resp)
    assert types_contain(events, "cache_hit"), events
    assert not fake.set_calls, "命中路径不该再写一次"
