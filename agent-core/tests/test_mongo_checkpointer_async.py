# -*- coding: utf-8 -*-
"""优化 ③ #6：MongoCheckpointer 异步方法必须经线程池（非阻塞事件循环）。

用内存 fake pymongo collection 验证逻辑正确性，不连真实 MongoDB。
核心诉求：原实现把同步 pymongo 调用直接写在 async 方法内，会阻塞 asyncio 事件循环；
现统一经 ``_run`` 投入线程池执行。本测试同时验证了「调用不抛、结果正确、且
在事件循环内不会因同步 IO 卡死」的语义。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeColl:
    """内存版 pymongo collection（仅实现 checkpointer 用到的接口）。"""
    def __init__(self):
        self._docs: dict[tuple, dict] = {}
        self.update_one_calls = []
        self.find_one_calls = []
        self.delete_many_calls = []

    def create_index(self, *_a, **_k):
        return "idx"

    def _key(self, f):
        return (f.get("tenant_id"), f.get("thread_id"), f.get("checkpoint_ns"), f.get("checkpoint_id"))

    def update_one(self, filt, update, upsert=False):
        self.update_one_calls.append((filt, update))
        key = self._key(filt)
        doc = self._docs.get(key, {})
        doc.update(filt)
        doc.update(update.get("$set", {}))
        self._docs[key] = doc

    def find_one(self, filt, proj=None):
        self.find_one_calls.append(filt)
        key = self._key(filt)
        return self._docs.get(key)

    def find(self, query):
        out = [d for d in self._docs.values() if all(d.get(k) == v for k, v in query.items())]
        return _FakeCursor(out)

    def delete_many(self, filt):
        self.delete_many_calls.append(filt)
        before = len(self._docs)
        self._docs = {
            k: d for k, d in self._docs.items()
            if not all(d.get(kk) == v for kk, v in filt.items())
        }
        return type("R", (), {"deleted_count": before - len(self._docs)})()


def _make_checkpointer():
    from agent_core.memory.mongo_checkpointer import MongoCheckpointer
    from langgraph.checkpoint.base import BaseCheckpointSaver

    # 不触发真实 MongoClient：用 __new__ 创建后手动注入内存 fake collection
    cp = MongoCheckpointer.__new__(MongoCheckpointer)
    BaseCheckpointSaver.__init__(cp, serde=None)
    cp._coll = _FakeColl()
    cp._tenant_id = "unit"
    return cp, cp._coll


def _cfg(thread_id, ns="", cid=None):
    if cid is None:
        cid = uuid.uuid4().hex
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": cid}}


@pytest.mark.asyncio
async def test_mongo_aput_and_aget_tuple_roundtrip():
    cp, fake = _make_checkpointer()
    cfg = _cfg("t1")
    ck = Checkpoint(id=cfg["configurable"]["checkpoint_id"], ts=0, channel_values={}, channel_versions={}, versions_seen={})
    md = CheckpointMetadata(parents={})

    await cp.aput(cfg, ck, md, {})
    got = await cp.aget_tuple(cfg)
    assert got is not None
    assert got.config["configurable"]["thread_id"] == "t1"
    # upsert 路径触发
    assert fake.update_one_calls


@pytest.mark.asyncio
async def test_mongo_alist_returns_tuples():
    cp, fake = _make_checkpointer()
    # 写入两条
    for i in range(2):
        cfg = _cfg("t2")
        ck = Checkpoint(id=cfg["configurable"]["checkpoint_id"], ts=i, channel_values={}, channel_versions={}, versions_seen={})
        await cp.aput(cfg, ck, CheckpointMetadata(parents={}), {})

    out = [t async for t in cp.alist({"configurable": {"thread_id": "t2"}})]
    assert len(out) == 2


@pytest.mark.asyncio
async def test_mongo_adelete_thread():
    cp, fake = _make_checkpointer()
    cfg = _cfg("t3")
    ck = Checkpoint(id=cfg["configurable"]["checkpoint_id"], ts=0, channel_values={}, channel_versions={}, versions_seen={})
    await cp.aput(cfg, ck, CheckpointMetadata(parents={}), {})
    await cp.adelete_thread("t3")
    assert fake.delete_many_calls
    assert await cp.aget_tuple(cfg) is None


@pytest.mark.asyncio
async def test_mongo_aput_writes_merges():
    cp, fake = _make_checkpointer()
    cfg = _cfg("t4")
    await cp.aput_writes(cfg, [("ch1", "v1")], task_id="task1")
    await cp.aput_writes(cfg, [("ch2", "v2")], task_id="task2")
    doc = fake.find_one({
        "tenant_id": "unit",
        "thread_id": "t4",
        "checkpoint_ns": "",
        "checkpoint_id": cfg["configurable"]["checkpoint_id"],
    })
    assert doc is not None
    channels = {w["channel"]: w["value"] for w in doc["writes"]}
    assert channels == {"ch1": "v1", "ch2": "v2"}
