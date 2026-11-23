# -*- coding: utf-8 -*-
"""刀 2 F-8：/collections 三接口带切分配置（GET 投影 / PATCH / POST）。

直接调路由函数，resolve_server_tenant 与 kb_collections 全 monkeypatch，零外部依赖。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from knowledge_service.api import import_router as ir

CFG = {"split_strategy": "char", "max_content_length": 1000, "chunk_overlap_ratio": 0.1}


def _tenant(monkeypatch):
    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "t1")


def test_list_collections_includes_chunk_config(monkeypatch) -> None:
    _tenant(monkeypatch)
    monkeypatch.setattr(
        ir.kb_collections, "list_by_tenant",
        lambda *a, **k: [{"knowledge_id": "kb-1", "name": "KB", "chunk_config": CFG}],
    )
    monkeypatch.setattr(ir, "get_milvus_client", lambda: None)  # 文档数降级 0
    resp = asyncio.run(ir.list_collections())
    assert resp["knowledge_bases"][0]["chunk_config"] == CFG


def test_create_collection_with_initial_config(monkeypatch) -> None:
    _tenant(monkeypatch)
    monkeypatch.setattr(
        ir.kb_collections, "create_collection",
        lambda **k: {"knowledge_id": "kb-new", "name": "KB"},
    )
    written = {}
    monkeypatch.setattr(
        ir.kb_collections, "update_chunk_config",
        lambda t, k, cfg: written.update(cfg) or True,
    )
    resp = asyncio.run(ir.create_collection({"name": "KB", "chunk_config": CFG}))
    assert resp["chunk_config"] == CFG
    assert written["split_strategy"] == "char"


def test_create_collection_rejects_bad_config(monkeypatch) -> None:
    _tenant(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ir.create_collection({"name": "KB", "chunk_config": {"max_content_length": 100}}))
    assert exc.value.status_code == 400


def test_update_collection_patch_config_only(monkeypatch) -> None:
    """PATCH 只传 chunk_config、不传 name 也应成功（原 rename 接口强制 name）。"""
    _tenant(monkeypatch)
    # M-1：update_collection 先查库存在，mock 掉避免真连 Mongo
    monkeypatch.setattr(
        ir.kb_collections, "get",
        lambda t, k: {"knowledge_id": k, "status": ir.kb_collections.STATUS_ACTIVE},
    )
    written = {}
    monkeypatch.setattr(
        ir.kb_collections, "update_chunk_config",
        lambda t, k, cfg: written.update(cfg) or True,
    )
    monkeypatch.setattr(ir.kb_collections, "rename_collection", lambda *a: True)
    resp = asyncio.run(ir.update_collection("kb-1", {"chunk_config": CFG}))
    assert resp["chunk_config"] == CFG
    assert "name" not in resp
    assert written["max_content_length"] == 1000


def test_update_collection_requires_something(monkeypatch) -> None:
    _tenant(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ir.update_collection("kb-1", {}))
    assert exc.value.status_code == 400


def test_update_collection_config_write_failure_returns_503(monkeypatch) -> None:
    """M-1：配置写失败须 503，不得假成功回显或误报 404。"""
    _tenant(monkeypatch)
    monkeypatch.setattr(
        ir.kb_collections, "get",
        lambda t, k: {"knowledge_id": k, "status": ir.kb_collections.STATUS_ACTIVE},
    )
    monkeypatch.setattr(ir.kb_collections, "update_chunk_config", lambda *a: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ir.update_collection("kb-1", {"chunk_config": CFG}))
    assert exc.value.status_code == 503


def test_create_collection_config_write_failure_marked(monkeypatch) -> None:
    """M-1：建库初始配置写失败须标注 chunk_config_applied=false，不回显假配置。"""
    _tenant(monkeypatch)
    monkeypatch.setattr(
        ir.kb_collections, "create_collection",
        lambda **k: {"knowledge_id": "kb-new", "name": "KB"},
    )
    monkeypatch.setattr(ir.kb_collections, "update_chunk_config", lambda *a: False)
    resp = asyncio.run(ir.create_collection({"name": "KB", "chunk_config": CFG}))
    assert resp["chunk_config_applied"] is False
    assert "chunk_config" not in resp  # 未写成功 → 不回显
