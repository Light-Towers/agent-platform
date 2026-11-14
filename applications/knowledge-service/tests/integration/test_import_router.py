# -*- coding: utf-8 -*-
"""import_router 端点契约测试（integration 套件）。

落点依据：api/import_router 模块导入即拉 main_graph 重型链（LangGraph 编译），
按仓库测试分层纪律（tests/unit/conftest + test_lifecycle_reimport.py:4「端点薄壳
不进 unit 套件」），这里归 integration。重型 import 全部放进测试函数体内，缺环境时
由 INTEGRATION_ENABLED 守卫跳过而非 ImportError。

钉三件事：
1. /status/{task_id} 响应形状（纯内存 task_utils，对齐 kb/datasources 转发纪律）；
2. /upload 在 MinIO 重试耗尽后 ⇒ 502 信封（DUP-7 关注的「重试耗尽→拒绝」行为，
   全部 mock，不依赖真实 MinIO）；
3. /upload 在 MinIO 成功 ⇒ 200 + task_ids 非空。

MinIO / copy_with_limit / run_graph_task / upsert_by_upload / resolve_server_tenant
全部 monkeypatch，避免触达真实对象存储与 LangGraph 全流程；PROJECT_ROOT 指向
tmp_path 避免在本仓库落盘 output/。
"""

import asyncio
import os

import pytest

INTEGRATION_ENABLED = os.environ.get("ZHIKU_INTEGRATION") == "1"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="requires ZHIKU_INTEGRATION=1 (heavy LangGraph import)")
def test_status_endpoint_shape(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import knowledge_service.api.import_router as ir
    import knowledge_service.utils.task_utils as tu

    # 后台任务打桩（避免真跑 LangGraph），其余端点内依赖本用例不触达
    monkeypatch.setattr(ir, "run_graph_task", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(ir.router)
    client = TestClient(app)

    tid = "integration-status-1"
    tu.update_task_status(tid, "completed")
    tu.add_done_task(tid, "upload_file")
    tu.add_running_task(tid, "chunking")

    resp = client.get(f"/status/{tid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["task_id"] == tid
    assert body["status"] == "completed"
    # done_list / running_list 是经「节点名→中文展示名」映射后的列表
    assert isinstance(body["done_list"], list) and len(body["done_list"]) == 1
    assert "开始上传文件" in body["done_list"]  # upload_file 节点中文展示名
    assert isinstance(body["running_list"], list) and len(body["running_list"]) == 1


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="requires ZHIKU_INTEGRATION=1 (heavy LangGraph import)")
def test_upload_minio_retry_exhausted_returns_502(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import knowledge_service.api.import_router as ir

    monkeypatch.setattr(ir, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ir, "run_graph_task", lambda *a, **k: None)
    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "tenant-test")
    monkeypatch.setattr(ir, "upsert_by_upload", lambda **k: True)
    monkeypatch.setattr(ir, "copy_with_limit", lambda *a, **k: None)  # 不真写盘

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)  # 跳过 1s/2s 退避，加速

    class _FailMinio:
        def fput_object(self, **kwargs):
            raise RuntimeError("minio unreachable")

    monkeypatch.setattr(ir, "get_minio_client", lambda: _FailMinio())

    app = FastAPI()
    app.include_router(ir.router)
    client = TestClient(app)

    resp = client.post(
        "/upload",
        files={"files": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 502, resp.text
    assert "Object storage unavailable" in resp.json()["detail"]


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="requires ZHIKU_INTEGRATION=1 (heavy LangGraph import)")
def test_upload_minio_success_returns_200(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import knowledge_service.api.import_router as ir

    monkeypatch.setattr(ir, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ir, "run_graph_task", lambda *a, **k: None)
    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "tenant-test")
    monkeypatch.setattr(ir, "upsert_by_upload", lambda **k: True)
    monkeypatch.setattr(ir, "copy_with_limit", lambda *a, **k: None)

    class _OkMinio:
        def fput_object(self, **kwargs):
            return None

    monkeypatch.setattr(ir, "get_minio_client", lambda: _OkMinio())

    app = FastAPI()
    app.include_router(ir.router)
    client = TestClient(app)

    resp = client.post(
        "/upload",
        files={"files": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    assert isinstance(body["task_ids"], list) and len(body["task_ids"]) == 1


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="requires ZHIKU_INTEGRATION=1 (heavy LangGraph import)")
def test_documents_endpoint_contract(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import knowledge_service.api.import_router as ir

    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "tenant-test")
    monkeypatch.setattr(
        ir, "list_by_tenant", lambda *a, **k: [{"knowledge_id": "k1", "filename": "a.pdf"}]
    )

    app = FastAPI()
    app.include_router(ir.router)
    client = TestClient(app)

    resp = client.get("/documents")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    assert body["tenant_id"] == "tenant-test"
    assert body["total"] == 1
    assert body["documents"][0]["knowledge_id"] == "k1"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="requires ZHIKU_INTEGRATION=1 (heavy LangGraph import)")
def test_reimport_endpoint_contract(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import knowledge_service.api.import_router as ir

    monkeypatch.setattr(ir, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ir, "run_graph_task", lambda *a, **k: None)
    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "tenant-test")
    monkeypatch.setattr(
        ir,
        "get_document",
        lambda *a, **k: {
            "knowledge_id": "k1",
            "tenant_id": "tenant-test",
            "status": "DRAFT",
            "local_file_path": "/x/a.pdf",
            "minio_object": "pdf_files/a.pdf",
            "metadata": {},
        },
    )
    monkeypatch.setattr(
        ir, "plan_reimport", lambda *a, **k: {"status": "REVIEWING", "tenant_id": "tenant-test"}
    )
    monkeypatch.setattr(ir, "resolve_original_file", lambda *a, **k: "/tmp/a.pdf")
    monkeypatch.setattr(ir, "get_minio_client", lambda: object())
    monkeypatch.setattr(ir, "update_status", lambda **k: None)

    app = FastAPI()
    app.include_router(ir.router)
    client = TestClient(app)

    resp = client.post("/reimport", data={"knowledge_id": "k1", "status": "REVIEWING"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    assert body["knowledge_id"] == "k1"
    assert body["to"] == "REVIEWING"
    assert "task_id" in body
