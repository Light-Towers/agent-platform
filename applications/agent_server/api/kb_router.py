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
from agent_runtime.identity import IdentityError, sign_internal_header
from agent_runtime.workspace_registry import asserted_user_id, server_tenant_id
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from agent_server.api.auth import require_feature, verify_api_key
from agent_server.config import get_settings
from agent_server.schemas import KbStatusRequest

router = APIRouter()

logger = get_logger(__name__)

#: 100MB 文件落盘 + MinIO put + 管线启动的预算（P11 上限对齐；不设显式超时大文件必挂）
_KS_TIMEOUT_S = 300.0


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


@router.post("/kb/uploads", summary="知识库文档上传（代理 KS /upload）")
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
    """多文件上传（kb.upload）：100MB 唯一硬校验在 KS 处理器（P11），代理不重复设限。"""
    url = _ks_base_url()
    settings = get_settings()
    asserted = server_tenant_id(settings.default_tenant_id)
    if tenant_id.strip() and tenant_id.strip() != asserted:
        raise AppError(403, "TENANT_MISMATCH", "表单租户与服务端断言不一致")

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
