# -*- coding: utf-8 -*-
"""重提入库纯决策逻辑（批 2a）单元测试：plan_reimport + resolve_original_file。

端点薄壳在 api/import_router（拉 main_graph 重型链，不进 unit 套件）；决策面在
utils/lifecycle_reimport（零重型依赖，本文件可每次 PR 必跑）。

钉七件事：
1. DRAFT→REVIEWING 合法迁移 ⇒ 通过，metadata 合并 tenant_id/status；
2. 未知状态码 ⇒ 400 具名；
3. DRAFT→PUBLISHED（跳过提审）⇒ 400 非法迁移（VALID_TRANSITIONS 契约）；
4. REVIEWING→PUBLISHED 缺 authority/effective_from/effective_to ⇒ 400 逐条列缺项；
5. 三字段覆盖生效（空串 = 沿用登记值，不覆盖）；
6. resolve_original_file：本地在则直接用（零 MinIO 触达）；
7. resolve_original_file：本地不在 ⇒ 409（无对象记录）/ 502（client None / fget 失败）。
"""

from __future__ import annotations

import os

import pytest

from knowledge_service.utils.lifecycle_reimport import ReimportError, plan_reimport, resolve_original_file

_BASE_META = {
    "scope_type": "PRIVATE",
    "tenant_type": "enterprise",
    "effective_from": "",
    "effective_to": "",
    "version": "v1",
    "authority": "",
    "status": "DRAFT",
    "constraint_kind": "",
    "enable_item_name_recognition": True,
    "exhibition_id": "EX-1",
    "venue_id": "",
}


def _record(status: str = "DRAFT", **overrides) -> dict:
    meta = {**_BASE_META, **overrides}
    return {
        "knowledge_id": "k-1",
        "tenant_id": "tenant-a",
        "scope_type": meta["scope_type"],
        "task_id": "t-1",
        "filename": "a.pdf",
        "local_dir": "/data/output/20261112/t-1",
        "local_file_path": "/data/output/20261112/t-1/a.pdf",
        "minio_object": "pdf_files/20261112/a.pdf",
        "metadata": meta,
        "status": status,
    }


def test_draft_to_reviewing_passes_and_merges():
    meta = plan_reimport(_record(), tenant_id="tenant-a", status="REVIEWING")
    assert meta["status"] == "REVIEWING"
    assert meta["tenant_id"] == "tenant-a"
    assert meta["knowledge_id"] == "k-1"
    assert meta["exhibition_id"] == "EX-1", "登记值沿用（空覆盖串不冲掉既有值）"


def test_unknown_status_400():
    with pytest.raises(ReimportError) as e:
        plan_reimport(_record(), tenant_id="t", status="ARCHIVED")
    assert e.value.status_code == 400
    assert "未知状态" in e.value.detail


def test_draft_to_published_skips_reviewing_400():
    """跳档发布（DRAFT→PUBLISHED）不在 VALID_TRANSITIONS ⇒ 400。"""
    with pytest.raises(ReimportError) as e:
        plan_reimport(_record(), tenant_id="t", status="PUBLISHED")
    assert e.value.status_code == 400
    assert "非法迁移" in e.value.detail and "DRAFT → PUBLISHED" in e.value.detail


def test_publish_missing_fields_listed_individually():
    """PUBLISHED 前置校验：缺哪些列哪些（authority/effective_from/effective_to）。"""
    with pytest.raises(ReimportError) as e:
        plan_reimport(
            _record(status="REVIEWING"),
            tenant_id="tenant-a",
            status="PUBLISHED",
            authority="",
            effective_from="",
            effective_to="",
        )
    assert e.value.status_code == 400
    for field in ("authority", "effective_from", "effective_to"):
        assert f"缺必填字段: {field}" in e.value.detail


def test_publish_with_overrides_passes_and_overrides_apply():
    meta = plan_reimport(
        _record(status="REVIEWING"),
        tenant_id="tenant-a",
        status="PUBLISHED",
        authority="cma",
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    assert meta["status"] == "PUBLISHED"
    assert meta["authority"] == "cma"
    assert meta["effective_from"] == "2026-01-01" and meta["effective_to"] == "2027-01-01"


def test_overrides_empty_keeps_registered_value():
    """空覆盖串 = 沿用登记值：authority 登记过则 PUBLISHED 校验吃登记值通过。"""
    meta = plan_reimport(
        _record(status="REVIEWING", authority="cma", effective_from="2026-01-01", effective_to="2027-01-01"),
        tenant_id="tenant-a",
        status="PUBLISHED",
    )
    assert meta["authority"] == "cma"
    assert meta["effective_from"] == "2026-01-01"


def test_resolve_prefers_existing_local_file(monkeypatch):
    monkeypatch.setattr("knowledge_service.utils.lifecycle_reimport.os.path.exists", lambda p: True)

    class _Boom:  # 本地命中时绝不允许触达 MinIO
        def fget_object(self, *a, **k):
            raise AssertionError("本地文件在则不该碰对象存储")

    path = resolve_original_file(_record(), "/tmp/new-task-dir", minio_client=_Boom())
    assert path == "/data/output/20261112/t-1/a.pdf"


def test_resolve_409_when_nothing_left(monkeypatch):
    monkeypatch.setattr("knowledge_service.utils.lifecycle_reimport.os.path.exists", lambda p: False)
    with pytest.raises(ReimportError) as e:
        resolve_original_file({**_record(), "minio_object": ""}, "/tmp/new-task-dir", minio_client=object())
    assert e.value.status_code == 409
    assert "原文已不在" in e.value.detail


def test_resolve_502_when_minio_unavailable(monkeypatch):
    monkeypatch.setattr("knowledge_service.utils.lifecycle_reimport.os.path.exists", lambda p: False)
    with pytest.raises(ReimportError) as e:
        resolve_original_file(_record(), "/tmp/new-task-dir", minio_client=None)
    assert e.value.status_code == 502
    assert "对象存储不可用" in e.value.detail


def test_resolve_restores_from_minio_into_new_task_dir(monkeypatch):
    monkeypatch.setattr("knowledge_service.utils.lifecycle_reimport.os.path.exists", lambda p: False)

    captured = {}

    class _FakeMinio:
        def fget_object(self, bucket, object_name, file_path):
            captured.update(bucket=bucket, object_name=object_name, file_path=file_path)

    path = resolve_original_file(_record(), "/tmp/new-task-dir", minio_client=_FakeMinio())
    assert path == os.path.join("/tmp/new-task-dir", "a.pdf"), "取回落新任务目录（旧目录产物不污染）"
    assert captured["object_name"] == "pdf_files/20261112/a.pdf"


def test_resolve_502_when_fget_fails(monkeypatch):
    monkeypatch.setattr("knowledge_service.utils.lifecycle_reimport.os.path.exists", lambda p: False)

    class _BrokenMinio:
        def fget_object(self, *a, **k):
            raise RuntimeError("bucket gone")

    with pytest.raises(ReimportError) as e:
        resolve_original_file(_record(), "/tmp/new-task-dir", minio_client=_BrokenMinio())
    assert e.value.status_code == 502
