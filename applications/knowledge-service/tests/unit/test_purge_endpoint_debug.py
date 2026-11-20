# -*- coding: utf-8 -*-
"""purge 端点：异常发生在切片已删之后 ⇒ 仍返回 200（用户视角：文档已删掉）。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from knowledge_service.api import import_router as ir
    from knowledge_service.main import app

    class FakeClient:
        def query(self, **kw): return []   # 删后复查：无残留
        def delete(self, **kw): pass
        def insert(self, **kw): pass

    monkeypatch.setattr(ir, "get_milvus_client", lambda: FakeClient())
    monkeypatch.setattr(ir, "resolve_server_tenant", lambda *a, **k: "default")
    return TestClient(app, raise_server_exceptions=False)


def test_purge_registry_error_after_delete_still_200(client, monkeypatch):
    """切片已删但 registry 回调抛异常 ⇒ 端点返回 200（删除目标已达成）。"""
    from knowledge_service.api import import_router as ir

    def boom(*a, **k):
        raise RuntimeError("registry 清理异常（模拟）")
    monkeypatch.setattr(ir.kb_delete, "purge_document", boom)

    r = client.delete("/documents/kb1/purge?source_doc=docA", headers={"X-Internal-Tenant": "default"})
    print("STATUS", r.status_code, "BODY", r.text[:200])
    assert r.status_code == 200, r.text


def test_purge_missing_returns_404(client, monkeypatch):
    from knowledge_service.api import import_router as ir
    monkeypatch.setattr(ir.kb_delete, "purge_document", lambda *a, **k: {
        "found": False, "deleted_chunks": 0, "registry_deleted": False, "source_doc": "x"})
    r = client.delete("/documents/kb1/purge?source_doc=x", headers={"X-Internal-Tenant": "default"})
    assert r.status_code == 404, r.text
