"""SQL 训练数据路由：改转发 nl2sql-service（A 方案 Stage ③）。

**行为变化（ADR-0011 选项 A）**：此前本端点把 DDL/文档/范例写进 agent_server
自管的 `sql_ddl`/`sql_docs`/`sql_examples` 三表（Vanna 式训练）；该路已退役，
统一到 nl2sql-service 的元知识库。本端点保持**对外契约不变**（路径、鉴权、
请求/响应形状），内部改为 POST `/api/meta/ingest`（同一套写入 core 的在线入口）。

- 隔离契约（ADR-0006/0007）不变：tenant_id 取服务端上下文（不收请求体字段），
  workspace_id 由请求体携带（归属维，缺省 default），写入前先经归属注册；
  解析出的作用域随摄入请求透传，nl2sql 侧按其自身优先级（服务端断言 > 请求体
  > default）落地。
- 响应新增可选 `report` 字段：摄入计数 + 三类记账（坏 DDL/未命中文档/空
  question）。布尔 flag 语义为"该输入已摄入（含跳过记账）"——精确到行的结果
  看 report；历史调用方只读 flag 的行为不变。
"""

from agent_runtime.db import get_pool
from agent_runtime.workspace_registry import resolve_workspace, server_tenant_id
from fastapi import APIRouter, Depends, HTTPException

from agent_server.api.auth import verify_api_key
from agent_server.config import get_settings
from agent_server.schemas import SqlTrainRequest, SqlTrainResponse

router = APIRouter()

#: 摄入含批量向量化（DDL 列 × embedding），比查询路慢——给 60s
_INGEST_TIMEOUT_S = 60.0


@router.post("/sql/train", response_model=SqlTrainResponse)
async def sql_train(
    req: SqlTrainRequest,
    _auth=Depends(verify_api_key),  # 仅作鉴权闸门（函数体不取凭据值，lint P12）
):
    settings = get_settings()
    url = settings.nl2sql_service_url
    if not url:
        raise HTTPException(
            status_code=503, detail="问数服务未配置（NL2SQL_SERVICE_URL 为空），无法摄入训练数据"
        )
    if not (req.ddl or req.documentation or (req.question and req.sql)):
        raise HTTPException(
            status_code=400, detail="至少提供 ddl / documentation / (question+sql) 之一"
        )
    tenant_id = server_tenant_id(settings.default_tenant_id)
    ws = req.workspace_id or "default"
    pool = get_pool()
    if pool is not None:
        await resolve_workspace(pool, tenant_id, ws)

    payload: dict = {"tenant_id": tenant_id, "workspace_id": ws}
    if req.ddl:
        payload["ddl"] = req.ddl
    if req.documentation:
        payload["docs"] = req.documentation
    if req.question and req.sql:
        payload["examples"] = [{"question": req.question, "sql": req.sql}]

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_INGEST_TIMEOUT_S) as client:
            resp = await client.post(f"{url}/api/meta/ingest", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"问数服务不可达（{type(exc).__name__}）：{url}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code, detail=f"nl2sql 摄入失败：{resp.text[:200]}"
        )
    report = resp.json()

    out = SqlTrainResponse()
    out.ddl_stored = bool(req.ddl)
    out.doc_stored = bool(req.documentation)
    out.example_stored = bool(req.question and req.sql)
    out.report = report  # type: ignore[attr-defined]
    return out
