# -*- coding: utf-8 -*-
"""kb_upload_history 上传历史持久化单测（集合注入缝，零 Mongo 依赖）。

钉四件事：
1. task_id 唯一键 upsert，$set/$setOnInsert 分离（首次写 uploaded_at，后续只更动态字段）；
2. summary / error 被完整写入（切块读数持久化的核心判据）；
3. 存储失败 → 返回 False 不抛（观测面不拦上传）；
4. list_by_tenant 租户过滤 + uploaded_at 降序 + limit + 剥 _id。
"""

from __future__ import annotations

from pymongo.errors import ConnectionFailure

from knowledge_service.utils import kb_upload_history


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
    def __init__(self, fail: bool = False):
        self.store: dict = {}
        self.fail = fail
        self.updates: list = []

    def update_one(self, query, update, upsert=False):
        if self.fail:
            raise ConnectionFailure("mongo down")
        self.updates.append((query, update, upsert))
        key = query["task_id"]
        doc = dict(self.store.get(key, {}))
        doc.update(update.get("$set", {}))
        if key not in self.store:
            doc.update(update.get("$setOnInsert", {}))
        self.store[key] = doc

    def find(self, query, projection=None):
        assert projection == {"_id": 0}
        return _FakeCursor([d for d in self.store.values() if d.get("tenant_id") == query["tenant_id"]])


_SUMMARY = {
    "split": {"md_lines": 777, "chunk_count": 36, "title_count": 93},
    "structure_check": {"md_chars": 27100, "chunk_chars": 27169, "char_coverage": 1.0025},
}


def test_record_upload_persists_summary_error_and_task_key():
    col = _FakeCollection()
    ok = kb_upload_history.record_upload(
        task_id="t-1", tenant_id="acme", filename="知识图谱.pdf",
        metadata={"knowledge_id": "", "scope_type": "PUBLIC", "status": "DRAFT"},
        status="completed", summary=_SUMMARY, error="", collection=col,
    )
    assert ok is True
    query, update, upsert = col.updates[-1]
    assert upsert is True and query == {"task_id": "t-1"}
    doc = update["$set"]
    assert doc["filename"] == "知识图谱.pdf"
    assert doc["summary"] == _SUMMARY
    assert doc["error"] == ""
    assert doc["knowledge_id"] == ""  # 默认上传 knowledge_id 空也照记（与 /documents 的区别）
    assert "uploaded_at" in update["$setOnInsert"]
    assert "created_at" in update["$setOnInsert"]


def test_record_upload_failure_is_non_blocking():
    ok = kb_upload_history.record_upload(
        task_id="t-2", tenant_id="acme", filename="a.pdf",
        metadata={}, status="failed", error="PDF 解析失败", collection=_FakeCollection(fail=True),
    )
    assert ok is False  # 不抛


def test_list_by_tenant_filters_and_sorts():
    col = _FakeCollection()
    col.store["t1"] = {"task_id": "t1", "tenant_id": "acme", "uploaded_at": "2026-01-01"}
    col.store["t2"] = {"task_id": "t2", "tenant_id": "other", "uploaded_at": "2026-01-02"}
    col.store["t3"] = {"task_id": "t3", "tenant_id": "acme", "uploaded_at": "2026-01-03"}
    rows = kb_upload_history.list_by_tenant("acme", limit=5, collection=col)
    assert [r["task_id"] for r in rows] == ["t3", "t1"]


def test_record_upload_rejects_empty_task_id():
    assert kb_upload_history.record_upload(
        task_id="", tenant_id="acme", filename="a.pdf", metadata={}, status="completed",
        collection=_FakeCollection(),
    ) is False
