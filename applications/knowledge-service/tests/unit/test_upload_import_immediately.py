# -*- coding: utf-8 -*-
"""上传即入库：DRAFT/REVIEWING/PUBLISHED 都写入 Milvus，只有 REVOKED 跳过。

回归 2026-11-19「上传解析成功但刷新后文档没了」：旧逻辑用
should_publish_to_production 挡住非 PUBLISHED（前端默认 DRAFT），切片不写库。
"""
from __future__ import annotations

from knowledge_service.import_process.agent.nodes.node_import_milvus import should_skip_import


def test_draft_uploads_now_import():
    """前端上传默认 DRAFT —— 必须入库（这是本次 bug 的直接回归）。"""
    assert should_skip_import({"status": "DRAFT"}) is False
    assert should_skip_import({"status": "REVIEWING"}) is False
    assert should_skip_import({"status": "PUBLISHED"}) is False


def test_empty_status_imports():
    """未指定状态按 DRAFT 处理，也入库。"""
    assert should_skip_import({}) is False
    assert should_skip_import({"status": ""}) is False


def test_revoked_skips():
    """删除态不重新入库。"""
    assert should_skip_import({"status": "REVOKED"}) is True
    assert should_skip_import({"status": "revoked"}) is True


def test_other_active_states_import():
    assert should_skip_import({"status": "EXPIRED"}) is False
    assert should_skip_import({"status": "SUPERSEDED"}) is False
