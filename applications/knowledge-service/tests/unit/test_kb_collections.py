# -*- coding: utf-8 -*-
"""知识库注册表单测（集合注入缝，零 Mongo 依赖）。

钉五件事：
1. knowledge_id/tenant 为空 ⇒ 不建库（返回 False，集合零调用）；
2. ensure_collection 幂等 upsert：(tenant,knowledge) 键 + $set(updated_at)/$setOnInsert(创建字段) 分离；
3. 存储失败 ⇒ 返回 False 不抛（上传链路不被 Mongo 单点拦死）；
4. list_by_tenant 默认排除 deleted、租户过滤、updated_at 降序、limit；
5. mark_deleted 只改 active 行、命中判定；失败不抛。
"""
from __future__ import annotations

from pymongo.errors import ConnectionFailure

from knowledge_service.utils import kb_collections


class _Result:
    def __init__(self, matched: int = 0):
        self.matched_count = matched


class _FakeCollection:
    def __init__(self, rows=None, fail: bool = False):
        self.rows = list(rows or [])
        self.fail = fail
        self.updates: list = []

    def insert_one(self, doc):
        if self.fail:
            raise ConnectionFailure("mongo down")
        self.rows.append(dict(doc))
        return type("_R", (), {"inserted_id": "x"})()

    def update_one(self, query, update, upsert=False):
        if self.fail:
            raise ConnectionFailure("mongo down")
        self.updates.append((query, update, upsert))
        match = next(
            (r for r in self.rows
             if all(r.get(k) == v for k, v in query.items())),
            None,
        )
        if match is None and upsert:
            doc = dict(query)
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            self.rows.append(doc)
            return _Result(0)
        if match is not None:
            match.update(update.get("$set", {}))
            return _Result(1)
        return _Result(0)

    def find_one(self, query, projection=None):
        return next(
            (dict(r) for r in self.rows if all(r.get(k) == v for k, v in query.items())),
            None,
        )

    def find(self, query, projection=None):
        items = [dict(r) for r in self.rows if all(r.get(k) == v for k, v in query.items())]
        return _Cursor(items)


class _Cursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, key, direction):
        self._items.sort(key=lambda d: d.get(key, ""), reverse=direction < 0)
        return self

    def limit(self, n):
        self._items = self._items[:n]
        return self

    def __iter__(self):
        return iter(self._items)


def test_empty_id_or_tenant_noop():
    col = _FakeCollection()
    assert kb_collections.ensure_collection(tenant_id="", knowledge_id="k", collection=col) is False
    assert kb_collections.ensure_collection(tenant_id="t", knowledge_id="  ", collection=col) is False
    assert col.updates == []


def test_ensure_upsert_shape():
    col = _FakeCollection()
    assert kb_collections.ensure_collection(
        tenant_id="t", knowledge_id="kb1", name="MyKB", owner="alice", collection=col
    ) is True
    query, update, upsert = col.updates[0]
    assert query == {"tenant_id": "t", "knowledge_id": "kb1"}
    assert upsert is True
    assert "updated_at" in update["$set"]
    on_insert = update["$setOnInsert"]
    assert on_insert["status"] == kb_collections.STATUS_ACTIVE
    assert on_insert["doc_count"] == 0
    assert on_insert["name"] == "MyKB"
    assert on_insert["owner"] == "alice"


def test_ensure_idempotent_keeps_created_fields():
    col = _FakeCollection()
    kb_collections.ensure_collection(tenant_id="t", knowledge_id="kb1", owner="first", collection=col)
    kb_collections.ensure_collection(tenant_id="t", knowledge_id="kb1", owner="second", collection=col)
    row = kb_collections.get("t", "kb1", collection=col)
    assert row["owner"] == "first"   # $setOnInsert 不覆盖
    assert len(col.rows) == 1


def test_write_failure_no_raise():
    col = _FakeCollection(fail=True)
    assert kb_collections.ensure_collection(tenant_id="t", knowledge_id="kb1", collection=col) is False
    assert kb_collections.mark_deleted("t", "kb1", collection=col) is False


def test_list_excludes_deleted_and_filters_tenant():
    rows = [
        {"tenant_id": "t", "knowledge_id": "a", "status": "active", "updated_at": "2026-01-01"},
        {"tenant_id": "t", "knowledge_id": "b", "status": "deleted", "updated_at": "2026-02-01"},
        {"tenant_id": "other", "knowledge_id": "c", "status": "active", "updated_at": "2026-03-01"},
    ]
    col = _FakeCollection(rows)
    got = kb_collections.list_by_tenant("t", collection=col)
    assert [r["knowledge_id"] for r in got] == ["a"]
    all_got = kb_collections.list_by_tenant("t", include_deleted=True, collection=col)
    assert [r["knowledge_id"] for r in all_got] == ["b", "a"]  # updated_at 降序


def test_mark_deleted_only_active():
    col = _FakeCollection([
        {"tenant_id": "t", "knowledge_id": "a", "status": "active", "updated_at": "x"},
    ])
    assert kb_collections.mark_deleted("t", "a", collection=col) is True
    assert kb_collections.get("t", "a", collection=col)["status"] == "deleted"
    assert kb_collections.mark_deleted("t", "a", collection=col) is False  # 已 deleted，不再命中


def test_create_collection_generates_unique_kb_id():
    col = _FakeCollection()
    a = kb_collections.create_collection(tenant_id="t", name="产品手册", collection=col)
    b = kb_collections.create_collection(tenant_id="t", name="产品手册", collection=col)  # 同名
    assert a and b
    assert a["knowledge_id"].startswith("kb_")
    assert a["knowledge_id"] != b["knowledge_id"]  # 同名也生成不同 ID（全局唯一）
    assert a["name"] == "产品手册"
    assert a["status"] == "active"
    assert len(col.rows) == 2


def test_create_collection_rejects_empty():
    col = _FakeCollection()
    assert kb_collections.create_collection(tenant_id="t", name="  ", collection=col) is None
    assert kb_collections.create_collection(tenant_id="", name="x", collection=col) is None
    assert col.rows == []


# --- 切分配置 chunk_config 读写（刀 1）---

def test_get_chunk_config_none_when_unset():
    col = _FakeCollection([
        {"tenant_id": "t", "knowledge_id": "kb1", "status": "active"},
    ])
    assert kb_collections.get_chunk_config("t", "kb1", collection=col) is None
    assert kb_collections.get_chunk_config("t", "missing", collection=col) is None


def test_get_chunk_config_only_active():
    col = _FakeCollection([
        {"tenant_id": "t", "knowledge_id": "kb1", "status": "deleted",
         "chunk_config": {"split_strategy": "char"}},
    ])
    assert kb_collections.get_chunk_config("t", "kb1", collection=col) is None


def test_update_chunk_config_writes_and_matches_active():
    col = _FakeCollection([
        {"tenant_id": "t", "knowledge_id": "kb1", "status": "active"},
    ])
    cfg = {"split_strategy": "char", "max_content_length": 1000, "chunk_overlap_ratio": 0.1}
    assert kb_collections.update_chunk_config("t", "kb1", cfg, collection=col) is True
    assert kb_collections.get_chunk_config("t", "kb1", collection=col) == cfg
    assert kb_collections.update_chunk_config("t", "missing", cfg, collection=col) is False



def test_rename_collection_only_active():
    col = _FakeCollection([
        {"tenant_id": "t", "knowledge_id": "kb-1", "name": "old", "status": "active", "updated_at": "x"},
    ])
    assert kb_collections.rename_collection("t", "kb-1", "new", collection=col) is True
    assert kb_collections.get("t", "kb-1", collection=col)["name"] == "new"
    assert kb_collections.rename_collection("t", "kb-1", "", collection=col) is False  # 空名拒绝
    assert kb_collections.rename_collection("other", "kb-1", "x", collection=col) is False  # 跨租户不改
