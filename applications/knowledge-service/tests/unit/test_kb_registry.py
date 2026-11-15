# -*- coding: utf-8 -*-
"""kb_documents 注册表（批 2a）单元测试：集合注入缝，零 Mongo 依赖。

钉五件事（kb_registry 模块头注的三条边界 + 两函数形状）：
1. knowledge_id 为空 ⇒ 不登记（返回 False，集合零调用）；
2. 正常登记 ⇒ upsert=True 的 (tenant_id, knowledge_id) 键 + $set/$setOnInsert 分离；
3. 存储失败 ⇒ 返回 False 不抛（上传链路不被 Mongo 单点拦死）；
4. get_document/list_by_tenant 的查询形状（租户过滤 + updated_at 降序 + limit）；
5. update_status 回写 $set 三字段；失败不抛。
"""

from __future__ import annotations

import pytest
from pymongo.errors import ConnectionFailure

from knowledge_service.utils import kb_registry


class _FakeCursor:
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


class _FakeCollection:
    """dict 存储的集合替身：记录 update_one 调用，支持注入失败（异常类可指定）。"""

    def __init__(self, fail: bool = False, exc: Exception | None = None):
        self.store: dict = {}
        self.fail = fail
        self.exc = exc or ConnectionFailure("mongo down")
        self.updates: list = []

    def update_one(self, query, update, upsert=False):
        if self.fail:
            raise self.exc
        self.updates.append((query, update, upsert))
        key = (query["tenant_id"], query["knowledge_id"])
        doc = dict(update.get("$set", {}))
        doc.update(update.get("$setOnInsert", {}))
        self.store[key] = doc

    def find_one(self, query):
        return self.store.get((query["tenant_id"], query["knowledge_id"]))

    def find(self, query, projection=None):
        items = [d for k, d in self.store.items() if k[0] == query["tenant_id"]]
        assert projection == {"_id": 0}, "列表面必须剥 _id"
        return _FakeCursor(items)


_RECORD = dict(
    tenant_id="tenant-a",
    knowledge_id="k-1",
    scope_type="PRIVATE",
    task_id="t-1",
    filename="a.pdf",
    local_dir="/data/output/20261112/t-1",
    local_file_path="/data/output/20261112/t-1/a.pdf",
    minio_object="pdf_files/20261112/a.pdf",
    metadata={"scope_type": "PRIVATE", "status": "DRAFT"},
    status="DRAFT",
)


def test_upsert_empty_knowledge_id_not_registered():
    """knowledge_id 为空 ⇒ 不登记（既有行为保持；该条不可重提）。"""
    col = _FakeCollection()
    ok = kb_registry.upsert_by_upload(collection=col, **{**_RECORD, "knowledge_id": "  "})
    assert ok is False
    assert col.updates == [], "空 id 不得触达集合"


def test_upsert_happy_path_shape():
    col = _FakeCollection()
    ok = kb_registry.upsert_by_upload(collection=col, **_RECORD)
    assert ok is True
    query, update, upsert = col.updates[0]
    assert query == {"tenant_id": "tenant-a", "knowledge_id": "k-1"}, "唯一键 = (tenant_id, knowledge_id)"
    assert upsert is True, "同键再传 = 覆盖（物理保证靠唯一索引 + upsert）"
    assert update["$set"]["task_id"] == "t-1"
    assert update["$set"]["status"] == "DRAFT"
    assert "created_at" in update["$setOnInsert"], "created_at 只在首插时写"
    assert "created_at" not in update["$set"], "覆盖时不得重置 created_at"


def test_upsert_storage_failure_returns_false_not_raises():
    """存储失败不拦上传：pymongo 异常族（连接/写失败）⇒ 返回 False，调用方只落日志。"""
    col = _FakeCollection(fail=True)
    ok = kb_registry.upsert_by_upload(collection=col, **_RECORD)
    assert ok is False


def test_upsert_non_pymongo_error_propagates():
    """宽捕收窄的反证面：非 pymongo 异常（序列化类编程错误）不吞——原样上抛。

    吞掉它 = 注册表静默丢数据；让它炸 = 编程错误当场暴露（诚实降级的边界在
    存储故障，不在代码 bug）。
    """
    col = _FakeCollection(fail=True, exc=RuntimeError("not a pymongo failure"))
    with pytest.raises(RuntimeError):
        kb_registry.upsert_by_upload(collection=col, **_RECORD)


def test_get_document_scoped_by_tenant():
    col = _FakeCollection()
    kb_registry.upsert_by_upload(collection=col, **_RECORD)
    doc = kb_registry.get_document("tenant-a", "k-1", collection=col)
    assert doc is not None and doc["task_id"] == "t-1"
    assert kb_registry.get_document("tenant-b", "k-1", collection=col) is None, "跨租户查不到（隔离边界）"


def test_list_by_tenant_sorted_desc_and_capped(monkeypatch):
    stamps = iter([f"2026-11-1{i}" for i in range(3)])
    monkeypatch.setattr(kb_registry, "_now_iso", lambda: next(stamps))
    col = _FakeCollection()
    for i in range(3):
        kb_registry.upsert_by_upload(collection=col, **{**_RECORD, "knowledge_id": f"k-{i}"})
    docs = kb_registry.list_by_tenant("tenant-a", limit=2, collection=col)
    assert len(docs) == 2, "limit 由调用方钳制"
    assert [d["knowledge_id"] for d in docs] == ["k-2", "k-1"], "updated_at 降序（最新在前）"


def test_update_status_writes_three_fields_and_tolerates_failure():
    col = _FakeCollection()
    kb_registry.upsert_by_upload(collection=col, **_RECORD)
    assert kb_registry.update_status(tenant_id="tenant-a", knowledge_id="k-1", status="REVIEWING", task_id="t-9", collection=col)
    doc = kb_registry.get_document("tenant-a", "k-1", collection=col)
    assert doc["status"] == "REVIEWING" and doc["task_id"] == "t-9"

    failing = _FakeCollection(fail=True)
    assert kb_registry.update_status(tenant_id="t", knowledge_id="k", status="PUBLISHED", task_id="x", collection=failing) is False


def test_real_module_lazy_singleton_not_touched_in_unit_env():
    """单例路径在 unit 环境不触发（注入缝的意义）：_store 仍为 None、零 Mongo 连接。"""
    assert kb_registry._store is None, "unit 套件不建立真连接（懒加载只在首个真实调用点发生）"
