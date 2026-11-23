# -*- coding: utf-8 -*-
"""/kb/* 代理用例。

1. 未配置 KNOWLEDGE_SERVICE_URL → 503（不静默）；
2. R5：Form tenant_id 非空且 ≠ 服务端断言租户 → AppError 403 TENANT_MISMATCH；
3. R5 正向：断言租户一致 ⇒ 转发，且转发的 form **不含 tenant_id**（KS 只见签名头）；
4. 未配 INTERNAL_HMAC_KEY ⇒ 503 拒发，零转发；
5. 签名头形状：X-Internal-Tenant；配了 KNOWLEDGE_SERVICE_KEY 才有 X-API-Key；
6. 上游不可达 → 502；上游 ≥400 → 状态码 + 文案透传；
7. PATCH /kb/{id}/status → KS POST /reimport（form 形状钉死）；
8. GET /kb/documents → KS GET /documents?limit=（透传 JSON）；
9. GET /kb/knowledge-bases → KS GET /collections?limit=（P1 改查库实体注册表）；
10. DELETE /kb/documents/{id} + DELETE /kb/knowledge-bases/{id} → KS（软删除/删库，含 409 透传）；
11. POST /kb/knowledge-bases + PATCH /kb/knowledge-bases/{id} → KS（新建/改名，body 透传）。
12. GET /kb/documents/tree → KS GET /documents/tree（库→文档→切片，数据源是 Milvus 实际切片）。
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agent_core.guardrails.errors import AppError
from agent_runtime.identity import IdentityError
from agent_server.api.kb_router import (
    kb_create_collection,
    kb_delete_collection,
    kb_delete_document,
    kb_documents,
    kb_documents_tree,
    kb_history,
    kb_knowledge_bases,
    kb_rename_collection,
    kb_status,
    kb_upload,
)
from agent_server.schemas import KbStatusRequest
from fastapi import HTTPException


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _Client:
    """捕获 POST/GET 的 (url, data/files/params, headers)，按脚本返回响应。"""

    def __init__(self, resp: _Resp, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc
        self.posts: list[tuple[str, dict, Any, dict | None]] = []
        self.gets: list[tuple[str, dict | None, dict | None]] = []
        self.deletes: list[tuple[str, dict | None]] = []
        self.delete_params: list[dict | None] = []
        self.patches: list[tuple[str, dict | None, dict | None]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, data: Any = None, **kwargs: Any) -> _Resp:
        self.posts.append((url, data or {}, kwargs.get("files"), kwargs.get("headers")))
        self.last_json = kwargs.get("json")
        if self._exc is not None:
            raise self._exc
        return self._resp

    async def patch(self, url: str, data: Any = None, **kwargs: Any) -> _Resp:
        self.patches.append((url, kwargs.get("json"), kwargs.get("headers")))
        if self._exc is not None:
            raise self._exc
        return self._resp

    async def get(self, url: str, params: dict | None = None, **kwargs: Any) -> _Resp:
        self.gets.append((url, params, kwargs.get("headers")))
        if self._exc is not None:
            raise self._exc
        return self._resp

    async def delete(self, url: str, **kwargs: Any) -> _Resp:
        self.deletes.append((url, kwargs.get("headers")))
        self.delete_params.append(kwargs.get("params"))
        if self._exc is not None:
            raise self._exc
        return self._resp


class _Up:
    """UploadFile 鸭子替身（直调端点不走 FastAPI 验证，只需 filename/file/content_type/read）。"""

    def __init__(self, filename: str = "a.pdf", content: bytes = b"pdf-bytes") -> None:
        self.filename = filename
        self.file = io.BytesIO(content)
        self.content_type = "application/pdf"

    async def read(self, n: int = -1) -> bytes:
        return self.file.read(n)


def _settings(url: str = "http://ks:8900", key: str = "", doc_backend: str = "milvus") -> MagicMock:
    s = MagicMock()
    s.knowledge_service_url = url
    s.knowledge_service_key = key
    s.default_tenant_id = "default-tenant"
    s.doc_backend = doc_backend
    return s


_UPLOAD_FORM = dict(
    tenant_id="",
    scope_type="PRIVATE",
    tenant_type="",
    effective_from="",
    effective_to="",
    version="",
    authority="",
    status="DRAFT",
    constraint_kind="",
    enable_item_name_recognition=True,
    knowledge_id="k-1",
    exhibition_id="",
    venue_id="",
    # 刀 2：切分参数（直接调用时显式传空值模拟 HTTP 未传）
    split_strategy="",
    max_content_length=0,
    chunk_overlap_ratio="",
)


@pytest.mark.parametrize("bad_id", ["", "   "])
async def test_upload_requires_knowledge_id_422(bad_id):
    """空/纯空格 knowledge_id → 422，且零转发（治本：无 ID 文档无法登记/检索）。"""
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()):
        with pytest.raises(HTTPException) as exc:
            await kb_upload(
                files=[_Up()], **{**_UPLOAD_FORM, "knowledge_id": bad_id},
                _auth=None, _feature=None,
            )
    assert exc.value.status_code == 422
    assert "KNOWLEDGE_ID_REQUIRED" in str(exc.value.detail)


async def test_upload_unconfigured_url_503():
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings("")):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 503


async def test_upload_cross_tenant_form_403():
    """R5：表单 tenant_id 非空且 ≠ 断言租户 ⇒ 403 TENANT_MISMATCH（信封统一）。"""
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()):
        with pytest.raises(AppError) as exc_info:
            await kb_upload(files=[_Up()], **{**_UPLOAD_FORM, "tenant_id": "other-tenant"}, _auth=None, _feature=None)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "TENANT_MISMATCH"


async def test_upload_forwards_files_and_strips_tenant_id():
    client = _Client(_Resp(200, {"code": 200, "message": "ok", "task_ids": ["t1"]}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_upload(files=[_Up()], **{**_UPLOAD_FORM, "tenant_id": "default-tenant"}, _auth=None, _feature=None)
    url, data, files, headers = client.posts[0]
    assert url == "http://ks:8900/upload"
    assert "tenant_id" not in data, "R5：归属走签名头，转发剥掉表单租户（KS 只见签名头）"
    assert data["scope_type"] == "PRIVATE"
    assert data["knowledge_id"] == "k-1"
    assert data["status"] == "DRAFT"
    assert data["enable_item_name_recognition"] == "true"
    assert files is not None and files[0][0] == "files", "多文件经 files= 转发（浏览器禁直连 KS，唯一入口在本代理）"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}, "未配 KNOWLEDGE_SERVICE_KEY ⇒ 只发签名头"
    assert resp == {"code": 200, "message": "ok", "task_ids": ["t1"]}, "KS 响应透传（契约形状不重造）"


async def test_upload_forwards_chunk_config_params():
    """刀 2：切分参数同名透传给 KS（校验/兜底在 KS 侧做）。"""
    client = _Client(_Resp(200, {"code": 200, "task_ids": ["t1"]}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        await kb_upload(
            files=[_Up()],
            **{**_UPLOAD_FORM, "split_strategy": "char", "max_content_length": 1500, "chunk_overlap_ratio": "0.2"},
            _auth=None, _feature=None,
        )
    _url, data, _files, _headers = client.posts[0]
    assert data["split_strategy"] == "char"
    assert data["max_content_length"] == "1500"
    assert data["chunk_overlap_ratio"] == "0.2"


async def test_upload_no_hmac_key_503_refuses_unsigned_forward():
    client = _Client(_Resp(200, {"code": 200, "task_ids": []}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch(
             "agent_server.api.kb_router.sign_internal_header",
             side_effect=IdentityError("未配置 INTERNAL_HMAC_KEY（内部签名头无法签发）"),
         ), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 503
    assert "INTERNAL_HMAC_KEY" in str(exc_info.value.detail)
    assert client.posts == [], "拒发即零转发——不能裸转未签名请求"


async def test_upload_service_key_becomes_api_key_header():
    """配了 KNOWLEDGE_SERVICE_KEY ⇒ X-API-Key 随签名头一起发（KS 护栏认这个头）。"""
    client = _Client(_Resp(200, {"code": 200, "task_ids": []}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings(key="ks-secret")), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    _, _, _, headers = client.posts[0]
    assert headers == {"X-Internal-Tenant": "v1.test.sig", "X-API-Key": "ks-secret"}


async def test_upload_upstream_unreachable_502():
    client = _Client(_Resp(200), exc=httpx.ConnectError("refused"))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 502


async def test_upload_upstream_error_status_propagates():
    """上游 4xx/5xx 原样透传（含 100MB 超限的 413 具名文案）。"""
    client = _Client(_Resp(413, text='{"detail":"文件超出上传上限（100 MB）"}'))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 413
    assert "100 MB" in str(exc_info.value.detail)


async def test_upload_pgvector_branch_writes_local_store_not_ks():
    """DOC_BACKEND=pgvector → 本地 DocumentStore 直写（断链修复点：不再转发 KS）。"""
    fake_store = MagicMock()
    fake_store.add_document = AsyncMock(return_value="docid1")
    client = _Client(_Resp(200, {"code": 200, "task_ids": ["t1"]}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings(doc_backend="pgvector")), \
         patch("agent_server.api.kb_router.get_document_store", return_value=fake_store), \
         patch("agent_server.api.kb_router.get_pool", return_value=object()), \
         patch("agent_server.api.kb_router.resolve_workspace", new_callable=AsyncMock), \
         patch("agent_server.api.kb_router.extract_text", return_value="# 标题\n正文"), \
         patch("agent_server.api.kb_router.split_markdown", return_value=[MagicMock(text="正文")]), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert resp["backend"] == "pgvector"
    assert resp["doc_ids"] == ["docid1"]
    assert resp["task_ids"] == [], "本地直写同步完成：无后台任务可轮询（前端据此跳过轮询）"
    assert client.posts == [], "pgvector 模式不得转发 KS（写检索不同源正是本次修复的断链）"
    args, kwargs = fake_store.add_document.call_args
    assert kwargs["tenant_id"] == "default-tenant"
    assert kwargs["knowledge_id"] == "k-1"


async def test_upload_unknown_backend_500():
    """DOC_BACKEND 拼写错误 → 500 当场暴露（配置错误不静默回落，与工厂同口径）。"""
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings(doc_backend="redis")):
        with pytest.raises(HTTPException) as exc_info:
            await kb_upload(files=[_Up()], **_UPLOAD_FORM, _auth=None, _feature=None)
    assert exc_info.value.status_code == 500
    assert "DOC_BACKEND" in str(exc_info.value.detail)


async def test_knowledge_bases_forwards_to_collections():
    """GET /kb/knowledge-bases：P1 改为代理 KS GET /collections（库实体注册表）。

    形状由 KS 侧保证（{knowledge_id, doc_count, status, ...}），平台只透传不聚合——
    聚合逻辑随 P1 移入 KS kb_collections，避免平台再扫 /documents。
    """
    payload = {"code": 200, "tenant_id": "default-tenant", "total": 2, "knowledge_bases": [
        {"knowledge_id": "kb-a", "name": "kb-a", "doc_count": 1, "status": "active", "latest_updated_at": "2026-11-18T08:00:00"},
        {"knowledge_id": "kb-b", "name": "kb-b", "doc_count": 0, "status": "active", "latest_updated_at": "2026-11-18T07:00:00"},
    ]}
    client = _Client(_Resp(200, payload))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_knowledge_bases(_auth=None, _feature=None)
    url, params, headers = client.gets[0]
    assert url == "http://ks:8900/collections"
    assert params == {"limit": 100}
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp["total"] == 2
    assert [k["knowledge_id"] for k in resp["knowledge_bases"]] == ["kb-a", "kb-b"]
    assert resp["knowledge_bases"][0]["status"] == "active"


async def test_status_forwards_to_reimport_with_form_shape():
    """PATCH /kb/{id}/status → KS POST /reimport（form：knowledge_id/status/三字段）。"""
    client = _Client(_Resp(200, {"code": 200, "knowledge_id": "k-1", "from": "REVIEWING", "to": "PUBLISHED", "task_id": "t9"}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_status(
            "k-1",
            KbStatusRequest(status="PUBLISHED", authority="cma", effective_from="2026-01-01", effective_to="2027-01-01"),
            _auth=None,
            _feature=None,
        )
    url, data, files, headers = client.posts[0]
    assert url == "http://ks:8900/reimport"
    assert data == {
        "knowledge_id": "k-1",
        "status": "PUBLISHED",
        "authority": "cma",
        "effective_from": "2026-01-01",
        "effective_to": "2027-01-01",
    }
    assert files is None, "reimport 无文件载荷"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp["task_id"] == "t9"


async def test_documents_forwards_get_with_limit():
    client = _Client(_Resp(200, {"code": 200, "tenant_id": "default-tenant", "total": 0, "documents": []}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        await kb_documents(limit=50, _auth=None, _feature=None)
    url, params, headers = client.gets[0]
    assert url == "http://ks:8900/documents"
    assert params == {"limit": 50}
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}


async def test_delete_document_proxies_to_ks():
    """DELETE /kb/documents/{id} → KS DELETE /documents/{id}（签名头透传）。"""
    client = _Client(_Resp(200, {"code": 200, "knowledge_id": "kb-x", "status": "REVOKED", "revoked_chunks": 1}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_delete_document("kb-x", _auth=None, _feature=None)
    url, headers = client.deletes[0]
    assert url == "http://ks:8900/documents/kb-x"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert client.delete_params[0] is None  # 不传 source_doc → 整库下线
    assert resp["status"] == "REVOKED"


async def test_delete_document_forwards_source_doc():
    """source_doc 给定时透传 KS query，实现「点单文档只下线该文档」。"""
    client = _Client(_Resp(200, {"code": 200, "status": "REVOKED"}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        await kb_delete_document("kb-x", source_doc="GBT45704.md", _auth=None, _feature=None)
    assert client.delete_params[0] == {"source_doc": "GBT45704.md"}


async def test_delete_collection_proxies_to_ks():
    """DELETE /kb/knowledge-bases/{id} → KS DELETE /collections/{id}。"""
    client = _Client(_Resp(200, {"code": 200, "knowledge_id": "kb-x", "status": "deleted"}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_delete_collection("kb-x", _auth=None, _feature=None)
    url, headers = client.deletes[0]
    assert url == "http://ks:8900/collections/kb-x"
    assert resp["status"] == "deleted"


async def test_delete_collection_proxies_409():
    """KS 409（库下有有效文档）原样回传。"""
    client = _Client(_Resp(409, text="库下仍有有效文档"))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        import pytest
        with pytest.raises(HTTPException) as ei:
            await kb_delete_collection("kb-x", _auth=None, _feature=None)
    assert ei.value.status_code == 409


async def test_history_forwards_get_with_limit():
    payload = {"code": 200, "tenant_id": "default-tenant", "total": 1,
               "items": [{"task_id": "t1", "filename": "a.pdf", "status": "completed", "summary": {}}]}
    client = _Client(_Resp(200, payload))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_history(limit=30, _auth=None, _feature=None)
    url, params, headers = client.gets[0]
    assert url == "http://ks:8900/history"
    assert params == {"limit": 30}
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp == payload


async def test_create_collection_proxies_post():
    """POST /kb/knowledge-bases → KS POST /collections（body + 签名头透传）。"""
    payload = {"code": 201, "knowledge_id": "kb_abc", "name": "产品手册"}
    client = _Client(_Resp(201, payload))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_create_collection({"name": "产品手册"}, _auth=None, _feature=None)
    url, _data, _files, headers = client.posts[0]
    assert url == "http://ks:8900/collections"
    assert client.last_json == {"name": "产品手册"}
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp["knowledge_id"] == "kb_abc"


async def test_rename_collection_proxies_patch():
    """PATCH /kb/knowledge-bases/{id} → KS PATCH /collections/{id}。"""
    client = _Client(_Resp(200, {"code": 200, "knowledge_id": "kb-1", "name": "新名"}))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_rename_collection("kb-1", {"name": "新名"}, _auth=None, _feature=None)
    url, body, headers = client.patches[0]
    assert url == "http://ks:8900/collections/kb-1"
    assert body == {"name": "新名"}
    assert resp["name"] == "新名"


async def test_documents_tree_proxies_get():
    """GET /kb/documents/tree → KS GET /documents/tree（库→文档→切片只读视图）。"""
    payload = {"code": 200, "tenant_id": "default-tenant", "total": 1, "knowledge_bases": [
        {"knowledge_id": "kb1", "doc_count": 1, "documents": [
            {"source_doc": "a.pdf", "chunk_count": 2, "chunks": [{"part": 0, "title": "h", "parent_title": "", "content": "c", "status": "PUBLISHED"}]}
        ]}
    ]}
    client = _Client(_Resp(200, payload))
    with patch("agent_server.api.kb_router.get_settings", return_value=_settings()), \
         patch("agent_server.api.kb_router.sign_internal_header", return_value="v1.test.sig"), \
         patch("httpx.AsyncClient", return_value=client):
        resp = await kb_documents_tree(_auth=None, _feature=None)
    url, params, headers = client.gets[0]
    assert url == "http://ks:8900/documents/tree"
    assert headers == {"X-Internal-Tenant": "v1.test.sig"}
    assert resp["knowledge_bases"][0]["doc_count"] == 1
