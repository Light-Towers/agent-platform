"""SQL 训练数据路由。

隔离契约（ADR-0006 T9/T10）：tenant_id 取服务端上下文（不收请求体字段）；
workspace_id 由请求体携带（归属维，缺省 default），写入前先经归属注册。
旧实现不传 workspace 落 ``''`` 空串桶且召回全库旁路，已随本项加固关闭。
"""

from agent_runtime.db import get_pool
from agent_runtime.workspace_registry import resolve_workspace, server_tenant_id
from fastapi import APIRouter, Depends, HTTPException

from agent_server.api.auth import verify_api_key
from agent_server.config import get_settings
from agent_server.schemas import SqlTrainRequest, SqlTrainResponse
from agent_server.sql.schema_store import store_ddl, store_doc, store_example

router = APIRouter()


@router.post("/sql/train", response_model=SqlTrainResponse)
async def sql_train(
    req: SqlTrainRequest,
    _auth=Depends(verify_api_key),  # 仅作鉴权闸门（函数体不取凭据值，lint P12）
):
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="训练数据存储未启用（DATABASE_URL 未配置）")
    if not (req.ddl or req.documentation or (req.question and req.sql)):
        raise HTTPException(
            status_code=400, detail="至少提供 ddl / documentation / (question+sql) 之一"
        )
    tenant_id = server_tenant_id(get_settings().default_tenant_id)
    ws = req.workspace_id or "default"
    await resolve_workspace(pool, tenant_id, ws)
    resp = SqlTrainResponse()
    if req.ddl:
        await store_ddl(pool, req.ddl, ws, tenant_id=tenant_id)
        resp.ddl_stored = True
    if req.documentation:
        await store_doc(pool, req.documentation, ws, tenant_id=tenant_id)
        resp.doc_stored = True
    if req.question and req.sql:
        await store_example(pool, req.question, req.sql, ws, tenant_id=tenant_id)
        resp.example_stored = True
    return resp
