"""SQL 训练数据路由。"""

from agent_runtime.db import get_pool
from fastapi import APIRouter, Depends, HTTPException

from agent_server.api.auth import verify_api_key
from agent_server.schemas import SqlTrainRequest, SqlTrainResponse
from agent_server.sql.schema_store import store_ddl, store_doc, store_example

router = APIRouter()


@router.post("/sql/train", response_model=SqlTrainResponse)
async def sql_train(req: SqlTrainRequest, api_key=Depends(verify_api_key)):
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="训练数据存储未启用（DATABASE_URL 未配置）")
    resp = SqlTrainResponse()
    if req.ddl:
        await store_ddl(pool, req.ddl)
        resp.ddl_stored = True
    if req.documentation:
        await store_doc(pool, req.documentation)
        resp.doc_stored = True
    if req.question and req.sql:
        await store_example(pool, req.question, req.sql)
        resp.example_stored = True
    if not (resp.ddl_stored or resp.doc_stored or resp.example_stored):
        raise HTTPException(
            status_code=400, detail="至少提供 ddl / documentation / (question+sql) 之一"
        )
    return resp
