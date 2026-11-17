"""知识库上传/发布代理（批 2a；方案 §4 D7 + 补记 9）。

三端点转发 knowledge-service（KS）：

- ``POST /kb/uploads``（feature ``kb.upload``）→ KS ``POST /upload``（13 Form 字段 + 多文件）
- ``PATCH /kb/{knowledge_id}/status``（feature ``kb.publish``）→ KS ``POST /reimport``
- ``GET /kb/documents``（feature ``kb.upload``）→ KS ``GET /documents``（列表读面）

隔离契约（R5）：tenant 取服务端断言（``X-Internal-Tenant`` 签名头传播）；表单里的
``tenant_id`` **声明是为了校验**（不声明则 FastAPI 静默丢弃，403 无从发生）——非空且
≠ 断言租户 ⇒ 403 ``TENANT_MISMATCH``；转发时**剥掉**（KS 只见签名头）。

浏览器禁直连 KS（G2 硬约束）：前端只打本代理，凭据头经 ``applyCredentialHeaders``
到 agent_server，本件再以内部签名头 + ``X-API-Key``（KNOWLEDGE_SERVICE_KEY）调 KS。

形状约束：**无构造器 prefix、装饰器写全路径**——齿 C5 的 provide 派生对构造器
prefix 不可见（补记 9 发现 3；auth/query/session 先例）。
"""

from typing import Any, Dict, List

from agent_core.guardrails.errors import AppError
from agent_core.logging import get_logger
from agent_runtime.db import get_pool
from agent_runtime.identity import IdentityError, sign_internal_header
from agent_runtime.workspace_registry import asserted_user_id, resolve_workspace, server_tenant_id
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from agent_server.api.auth import require_feature, verify_api_key
from agent_server.api.import_router import extract_text
from agent_server.config import get_settings
from agent_server.rag.backend import get_document_store
from agent_server.rag.chunker import split_markdown
from agent_server.schemas import KbStatusRequest

router = APIRouter()

logger = get_logger(__name__)

#: 100MB 文件落盘 + MinIO put + 管线启动的预算（P11 上限对齐；不设显式超时大文件必挂）
_KS_TIMEOUT_S = 300.0
#: pgvector 本地分支的单文件上限（与 KS P11 同值：两条上传链路同一条红线）
_LOCAL_UPLOAD_LIMIT = 100 * 1024 * 1024


def _ks_base_url() -> str:
    """KS 基址（未配置 ⇒ 503，与 sql_router 未配 URL 同形：不静默降级）。"""
    settings = get_settings()
    url = settings.knowledge_service_url
    if not url:
        raise HTTPException(
            status_code=503,
            detail="知识库服务未配置（KNOWLEDGE_SERVICE_URL 为空），无法转发",
        )
    return url.rstrip("/")


def _internal_headers() -> Dict[str, str]:
    """构造发往 KS 的头：租户签名头 + 服务间 API Key（配置了才发）。

    role **不签**：KS fork 的二元组验签「带而不用」（补记 9），签无消费者的键
    = 无主契约面。
    """
    settings = get_settings()
    tenant_id = server_tenant_id(settings.default_tenant_id)
    try:
        internal_header = sign_internal_header(tenant_id, asserted_user_id())
    except IdentityError as exc:
        # 未配 INTERNAL_HMAC_KEY ⇒ 拒发而非明文裸转（信任边界 B 对 KS 同样成立）。
        logger.info("internal header signing unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="内部签名头不可用：/kb/* 拒绝未签名转发，请配置 INTERNAL_HMAC_KEY(_FILE)",
        ) from exc
    headers = {"X-Internal-Tenant": internal_header}
    if settings.knowledge_service_key:
        headers["X-API-Key"] = settings.knowledge_service_key
    return headers


@router.post("/kb/uploads", summary="知识库文档上传（按 DOC_BACKEND 分流：pgvector 本地直写 / milvus 代理 KS）")
async def kb_upload(
    files: List[UploadFile] = File(...),
    # 13 Form 字段对齐 KS import_router（转发同名透传）；tenant_id 声明仅为 R5 校验，
    # 转发时剥掉（KS 侧归属只认签名头断言）。
    tenant_id: str = Form(""),
    scope_type: str = Form("PRIVATE"),
    tenant_type: str = Form(""),
    effective_from: str = Form(""),
    effective_to: str = Form(""),
    version: str = Form(""),
    authority: str = Form(""),
    status: str = Form("DRAFT"),
    constraint_kind: str = Form(""),
    enable_item_name_recognition: bool = Form(True),
    knowledge_id: str = Form(""),
    exhibition_id: str = Form(""),
    venue_id: str = Form(""),
    datasource_type: str = Form(""),
    _auth=Depends(verify_api_key),  # 仅作鉴权闸门（函数体不取凭据值，lint P12）
    _feature=Depends(require_feature("kb.upload")),  # 401 先于 403：_auth 必须在前
):
    """多文件上传（kb.upload）：100MB 唯一硬校验在 KS 处理器（P11），代理不重复设限。

    分流（plan-knowledge-base-model 的根因修复点：上传与检索必须落**同一个后端**）：
    - ``DOC_BACKEND=milvus``  → 代理 KS /upload（KS 管线写共享集合，含登记/发布管理）；
    - ``DOC_BACKEND=pgvector`` → 本地 DocumentStore 直写（写 KS 的 Milvus 而检索读
      pgvector 正是本次修复的断链，pgvector 模式下不再转发）。
    """
    # knowledge_id 必填（与 KS /upload 同契约）：在代理层也拦一道，
    # 空 ID 文档无法登记/发布/检索，提前 422 免得转发过去才失败。
    if not knowledge_id or not knowledge_id.strip():
        raise HTTPException(status_code=422, detail="KNOWLEDGE_ID_REQUIRED：知识库 ID 为必填项，用于文档登记与发布管理")
    knowledge_id = knowledge_id.strip()
    settings = get_settings()
    asserted = server_tenant_id(settings.default_tenant_id)
    if tenant_id.strip() and tenant_id.strip() != asserted:
        raise AppError(403, "TENANT_MISMATCH", "表单租户与服务端断言不一致")

    backend = settings.doc_backend
    if backend == "pgvector":
        return await _local_ingest(files, knowledge_id)
    if backend != "milvus":
        raise HTTPException(status_code=500, detail=f"未知 DOC_BACKEND: {backend}（可选 milvus | pgvector）")

    url = _ks_base_url()
    # 流式转发：UploadFile 的 spooled 文件对象直接进 httpx files=（不整体读进内存，
    # 100MB 请求不该在代理层再复制一份）。
    ks_files = []
    for f in files:
        ks_files.append(
            ("files", (f.filename or "", f.file, f.content_type or "application/octet-stream"))
        )
    data: Dict[str, Any] = {
        "scope_type": scope_type,
        "tenant_type": tenant_type,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "version": version,
        "authority": authority,
        "status": status,
        "constraint_kind": constraint_kind,
        "enable_item_name_recognition": "true" if enable_item_name_recognition else "false",
        "knowledge_id": knowledge_id,
        "exhibition_id": exhibition_id,
        "venue_id": venue_id,
        "datasource_type": datasource_type,
    }

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_KS_TIMEOUT_S) as client:
            resp = await client.post(f"{url}/upload", data=data, files=ks_files, headers=_internal_headers())
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"知识库服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"知识库上传失败：{resp.text[:200]}")
    return resp.json()


async def _local_ingest(files: List[UploadFile], knowledge_id: str) -> Dict[str, Any]:
    """pgvector 本地直写分支：经 DocumentStore 协议写当前后端（与 rag_query 同源）。

    同步完成（无后台任务）：返回 task_ids=[]，前端据此跳过轮询直接提示成功。
    """
    store = get_document_store()
    if store is None:
        raise HTTPException(status_code=503, detail="文档检索后端未配置（DOC_BACKEND）")
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="知识库未启用（DATABASE_URL 未配置）")
    tenant_id = server_tenant_id(get_settings().default_tenant_id)
    ws = "default"
    await resolve_workspace(pool, tenant_id, ws)

    doc_ids: List[str] = []
    sources: List[str] = []
    chunk_total = 0
    for f in files:
        filename = f.filename or "upload"
        raw = await f.read(_LOCAL_UPLOAD_LIMIT + 1)
        if len(raw) > _LOCAL_UPLOAD_LIMIT:
            raise HTTPException(
                status_code=413,
                detail=f"文件超出上传上限（{_LOCAL_UPLOAD_LIMIT // (1024 * 1024)} MB），请拆分后上传",
            )
        try:
            text = extract_text(filename, raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        chunks = split_markdown(text)
        if not chunks:
            raise HTTPException(status_code=400, detail=f"文档内容为空或无法切分: {filename}")
        doc_id = await store.add_document(
            pool, filename, chunks, ws, tenant_id=tenant_id, knowledge_id=knowledge_id
        )
        doc_ids.append(doc_id)
        sources.append(filename)
        chunk_total += len(chunks)
    logger.info(
        "pgvector 本地上传完成：knowledge_id=%s files=%s chunks=%s",
        knowledge_id, len(sources), chunk_total,
    )
    return {
        "code": 200,
        "backend": "pgvector",
        "task_ids": [],  # 同步写完，无后台任务可轮询
        "doc_ids": doc_ids,
        "chunks": chunk_total,
        "sources": sources,
        "knowledge_id": knowledge_id,
        "message": "已写入本地文档向量库（无需轮询进度）",
    }


@router.patch("/kb/{knowledge_id}/status", summary="知识条目生命周期状态变更（代理 KS /reimport）")
async def kb_status(
    knowledge_id: str,
    req: KbStatusRequest,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("kb.publish")),  # 401 先于 403：_auth 必须在前
):
    """提审/发布（kb.publish）：转 KS ``POST /reimport``（按新状态重跑导入管线）。

    断言租户由签名头传播；KS 侧 /reimport 从第一天就只认断言（不收 Form tenant_id）。
    """
    url = _ks_base_url()

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_KS_TIMEOUT_S) as client:
            resp = await client.post(
                f"{url}/reimport",
                data={
                    "knowledge_id": knowledge_id,
                    "status": req.status,
                    "authority": req.authority,
                    "effective_from": req.effective_from,
                    "effective_to": req.effective_to,
                },
                headers=_internal_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"知识库服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"知识库重提失败：{resp.text[:200]}")
    return resp.json()


@router.get("/kb/documents", summary="登记文档列表（代理 KS /documents）")
async def kb_documents(
    limit: int = 100,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("kb.upload")),  # 401 先于 403：_auth 必须在前
):
    """租户内登记文档列表（kb.upload 方向的读面；KS 侧 limit≤100）。"""
    url = _ks_base_url()

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_KS_TIMEOUT_S) as client:
            resp = await client.get(
                f"{url}/documents", params={"limit": limit}, headers=_internal_headers()
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"知识库服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"知识库列表查询失败：{resp.text[:200]}")
    return resp.json()


@router.get("/kb/status/{task_id}", summary="上传任务进度（代理 KS /status/{task_id}）")
async def kb_status_get(
    task_id: str,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("kb.upload")),
):
    """上传后管线进度轮询（kb.upload 读面）；KS 侧 /status/{task_id} 返回任务状态/进度/错误。"""
    url = _ks_base_url()
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_KS_TIMEOUT_S) as client:
            resp = await client.get(
                f"{url}/status/{task_id}", headers=_internal_headers()
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"知识库服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"知识库状态查询失败：{resp.text[:200]}")
    return resp.json()


@router.get("/kb/history", summary="上传历史列表（代理 KS /history）")
async def kb_history(
    limit: int = 100,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("kb.upload")),  # 401 先于 403
):
    """租户内上传历史（每次上传一行，含切块读数；服务端权威，刷新/重启仍在）。"""
    url = _ks_base_url()
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_KS_TIMEOUT_S) as client:
            resp = await client.get(
                f"{url}/history", params={"limit": limit}, headers=_internal_headers()
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"知识库服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"上传历史查询失败：{resp.text[:200]}")
    return resp.json()


@router.get("/kb/knowledge-bases", summary="知识库列表（代理聚合 KS /documents，按 knowledge_id 去重）")
async def kb_knowledge_bases(
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("chat.run")),  # 消费方是对话区"知识范围"选择器，不是 kb 管理页
):
    """租户内知识库清单（plan-knowledge-base-model 步骤 4）：多库检索/选库的前端数据源。

    聚合规则：KS /documents 的登记文档按 ``knowledge_id`` 去重计数；``status`` 取该库
    最新一条登记的状态（KS /documents 按 updated_at 降序 ⇒ 首见即最新）。
    """
    url = _ks_base_url()

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_KS_TIMEOUT_S) as client:
            resp = await client.get(
                f"{url}/documents", params={"limit": 100}, headers=_internal_headers()
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"知识库服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"知识库列表查询失败：{resp.text[:200]}")

    docs = (resp.json() or {}).get("documents") or []
    agg: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        kid = str(d.get("knowledge_id") or "").strip()
        if not kid:
            continue  # 空 ID 未登记（历史遗留形状），不进知识库清单
        entry = agg.setdefault(
            kid,
            {
                "knowledge_id": kid,
                "doc_count": 0,
                "status": str(d.get("status") or ""),
                "latest_updated_at": str(d.get("updated_at") or ""),
            },
        )
        entry["doc_count"] += 1
    kbs = sorted(agg.values(), key=lambda e: e["knowledge_id"])
    return {"code": 200, "total": len(kbs), "knowledge_bases": kbs}
