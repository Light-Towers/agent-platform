"""数据源配置代理（G3 刀 3）：转发 nl2sql /api/meta/datasources*。

浏览器不直连 nl2sql（G3 硬约束）：前端只打本代理，经 verify_api_key +
require_feature("datasource.manage") 网关；本件再以 X-Internal-Tenant 签名头转发到
nl2sql 的 /api/meta/datasources。形状约束同 kb_router/sql_router：无构造器 prefix、
装饰器写全路径（齿 C5 的 provide 派生对构造器 prefix 不可见）。
"""
from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger
from agent_runtime.identity import IdentityError, sign_internal_header
from agent_runtime.workspace_registry import server_tenant_id
from fastapi import APIRouter, Depends, HTTPException, Request

from agent_server.api.auth import require_feature, verify_api_key
from agent_server.config import get_settings

router = APIRouter()

logger = get_logger(__name__)

_NL2SQL_TIMEOUT_S = 30.0


def _nl2sql_base() -> str:
    """nl2sql 基址（未配置 ⇒ 503，与 sql_router 同形：不静默降级）。"""
    settings = get_settings()
    url = settings.nl2sql_service_url
    if not url:
        raise HTTPException(
            status_code=503,
            detail="问数服务未配置（NL2SQL_SERVICE_URL 为空），无法转发数据源配置",
        )
    return url.rstrip("/")


def _internal_headers() -> dict[str, str]:
    """构造发往 nl2sql 的头：租户签名头（role 不签，同 kb_router 纪律）。"""
    settings = get_settings()
    tenant_id = server_tenant_id(settings.default_tenant_id)
    try:
        internal_header = sign_internal_header(tenant_id)
    except IdentityError as exc:
        logger.info("internal header signing unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="内部签名头不可用：/datasources 拒绝未签名转发，请配置 INTERNAL_HMAC_KEY(_FILE)",
        ) from exc
    return {"X-Internal-Tenant": internal_header}


async def _forward(method: str, path: str, body: Any = None) -> Any:
    import httpx

    url = f"{_nl2sql_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_NL2SQL_TIMEOUT_S) as client:
            resp = await client.request(method, url, json=body, headers=_internal_headers())
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"问数服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"数据源配置转发失败：{resp.text[:200]}")
    try:
        return resp.json()
    except ValueError:  # 上游返回非 JSON（JSONDecodeError 即 ValueError 子类）
        return {}


@router.get("/datasources", summary="数据源列表（代理 nl2sql /api/meta/datasources）")
async def proxy_list(
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("datasource.manage")),
):
    return await _forward("GET", "/api/meta/datasources")


@router.post("/datasources", summary="新建数据源（代理 nl2sql POST /api/meta/datasources）")
async def proxy_create(
    req: Request,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("datasource.manage")),
):
    body = await req.json()
    return await _forward("POST", "/api/meta/datasources", body)


@router.patch("/datasources/{ds_id}", summary="更新数据源（代理 nl2sql PATCH /api/meta/datasources/{id}）")
async def proxy_update(
    ds_id: str,
    req: Request,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("datasource.manage")),
):
    body = await req.json()
    return await _forward("PATCH", f"/api/meta/datasources/{ds_id}", body)


@router.post("/datasources/{ds_id}/default", summary="设默认源（代理 nl2sql POST /api/meta/datasources/{id}/default）")
async def proxy_set_default(
    ds_id: str,
    _auth=Depends(verify_api_key),
    _feature=Depends(require_feature("datasource.manage")),
):
    return await _forward("POST", f"/api/meta/datasources/{ds_id}/default")
