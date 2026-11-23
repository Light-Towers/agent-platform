# -*- coding: utf-8 -*-
"""上传 resolver：切分参数显式传参优先 / 未传读库配置兜底 / 非法值 400。

直接调 upload_files（参照 test_upload_requires_knowledge_id.py），把文件落盘/MinIO/
后台任务全 monkeypatch 掉，捕获 run_graph_task 的 metadata 断言切分参数。
"""
from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

from knowledge_service.api import import_router as ir


class _OkMinio:
    def fput_object(self, **kwargs):
        return None


def _file() -> UploadFile:
    return UploadFile(filename="a.pdf", file=io.BytesIO(b"pdf-bytes"))


class _EagerBackgroundTasks(BackgroundTasks):
    """add_task 时立即执行 fn，便于捕获 run_graph_task 的 metadata。"""

    def __init__(self, captured):
        super().__init__()
        self._captured = captured

    def add_task(self, func, *args, **kwargs):
        func(*args, **kwargs)


def _setup(monkeypatch, tmp_path, stored_cfg):
    captured = {}
    monkeypatch.setattr(ir, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "t1")
    monkeypatch.setattr(ir, "get_minio_client", lambda: _OkMinio())
    monkeypatch.setattr(ir, "copy_with_limit", lambda *a, **k: None)
    monkeypatch.setattr(ir, "upsert_by_upload", lambda **k: True)
    monkeypatch.setattr(ir.kb_collections, "ensure_collection", lambda **k: True)
    monkeypatch.setattr(ir.kb_collections, "get_chunk_config", lambda *a, **k: stored_cfg)
    monkeypatch.setattr(ir, "add_running_task", lambda *a, **k: None)
    monkeypatch.setattr(ir, "add_done_task", lambda *a, **k: None)

    def _capture(task_id, local_dir, local_path, metadata):
        captured.update(metadata)

    monkeypatch.setattr(ir, "run_graph_task", _capture)
    return captured, _EagerBackgroundTasks(captured)


def _call(bg, **kwargs):
    # 直接调用函数时 Form 默认值是 Form 对象（真实 HTTP 下 FastAPI 会物化为 ""/0）
    # ⇒ 显式传空值模拟"HTTP 未传该字段"，否则 resolver 拿到 Form 对象会 float() 报错。
    defaults = dict(
        background_tasks=bg,
        files=[_file()],
        knowledge_id="kb-1",
        split_strategy="",
        max_content_length=0,
        chunk_overlap_ratio="",
    )
    defaults.update(kwargs)
    return asyncio.run(ir.upload_files(**defaults))


def test_datasource_type_defaults_empty_after_frontend_removal(monkeypatch, tmp_path) -> None:
    """M-A：前端砍掉 metadata 提交后 datasource_type 走 KS Form 默认空串（非旧的 'mysql'）。

    全仓无下游消费者，故空串是通用中立语义；此测试钉死口径防未来无声漂移。
    """
    captured, bg = _setup(monkeypatch, tmp_path, stored_cfg=None)
    _call(bg, datasource_type="")  # HTTP 未传该字段时 FastAPI 物化为空串
    assert captured["datasource_type"] == ""


def test_no_params_no_stored_uses_global_default(monkeypatch, tmp_path) -> None:
    captured, bg = _setup(monkeypatch, tmp_path, stored_cfg=None)
    _call(bg)
    assert captured["split_strategy"] == "title"
    assert captured["max_content_length"] == 2000
    assert captured["chunk_overlap"] == 200


def test_stored_config_used_when_no_explicit(monkeypatch, tmp_path) -> None:
    captured, bg = _setup(
        monkeypatch, tmp_path,
        stored_cfg={"split_strategy": "char", "max_content_length": 1000, "chunk_overlap_ratio": 0.1},
    )
    _call(bg)
    assert captured["split_strategy"] == "char"
    assert captured["max_content_length"] == 1000
    assert captured["chunk_overlap"] == 100


def test_explicit_params_override_stored(monkeypatch, tmp_path) -> None:
    captured, bg = _setup(
        monkeypatch, tmp_path,
        stored_cfg={"split_strategy": "char", "max_content_length": 1000, "chunk_overlap_ratio": 0.1},
    )
    _call(bg, split_strategy="line", max_content_length=1500, chunk_overlap_ratio="0.2")
    assert captured["split_strategy"] == "line"
    assert captured["max_content_length"] == 1500
    assert captured["chunk_overlap"] == 300


def test_partial_explicit_fills_rest_from_stored(monkeypatch, tmp_path) -> None:
    captured, bg = _setup(
        monkeypatch, tmp_path,
        stored_cfg={"split_strategy": "char", "max_content_length": 1000, "chunk_overlap_ratio": 0.1},
    )
    _call(bg, split_strategy="line")  # 只传策略，其余沿用库配置
    assert captured["split_strategy"] == "line"
    assert captured["max_content_length"] == 1000
    assert captured["chunk_overlap"] == 100


@pytest.mark.parametrize("bad", [
    {"split_strategy": "bogus"},
    {"max_content_length": 100},   # < 500
    {"chunk_overlap_ratio": "0.9"},  # > 0.5
    {"chunk_overlap_ratio": "abc"},  # 非数值
])
def test_invalid_params_return_400(monkeypatch, tmp_path, bad) -> None:
    _, bg = _setup(monkeypatch, tmp_path, stored_cfg=None)
    with pytest.raises(HTTPException) as exc:
        _call(bg, **bad)
    assert exc.value.status_code == 400


def test_run_graph_task_whitelist_injects_chunk_params(monkeypatch) -> None:
    """L-4：reimport 复用 run_graph_task，metadata 里的三参数须经白名单注入 init_state。"""
    captured = {}

    class _FakeApp:
        def stream(self, state):
            captured.update(state)
            return iter([])

    monkeypatch.setattr(ir, "kb_import_app", _FakeApp())
    monkeypatch.setattr(ir, "update_task_status", lambda *a, **k: None)
    monkeypatch.setattr(ir, "add_done_task", lambda *a, **k: None)
    monkeypatch.setattr(ir, "add_running_task", lambda *a, **k: None)

    # /reimport 从登记的 metadata 取回三参数（plan_reimport 原样透传）
    metadata = {
        "split_strategy": "char", "max_content_length": 1500, "chunk_overlap": 150,
    }
    ir.run_graph_task("t1", "/tmp/d", "/tmp/a.pdf", metadata)
    assert captured["split_strategy"] == "char"
    assert captured["max_content_length"] == 1500
    assert captured["chunk_overlap"] == 150
