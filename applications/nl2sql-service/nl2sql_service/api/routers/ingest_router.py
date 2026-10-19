"""POST /api/meta/ingest：训练数据在线摄入（A 方案 Stage ③，替代 agent_server /sql/train）。

**为什么需要**：agent_server 的 `/sql/train`（DDL/文档/范例即时进库）是上线端点
（2026-10-12 release runbook 有记录），agent_server/sql 退役后这条路不能断——
本端点用**同一套写入 core**（`services/ingest_service.write_scope`，与迁移 CLI
共用）把它接过来：DDL→column_info、文档→table_comment、范例→example_info。

**与迁移 CLI 的分工**：CLI 批量搬历史数据（读源库三表、多 scope、--prune）；
本端点管在线增量（一次一个作用域、不 prune——范例的差异删是显式运维动作，
不该被一次摄入顺带删掉）。

**隔离（#102 修订）**：本端点是**写面**，归属只认服务端断言——tenant 取自
`server_tenant_id()`（身份门 JWT / 内部签名头 / 单租户装配），无断言即 401
fail-fast，不落任何桶；**不接受请求体 tenant_id/workspace_id**（携带非空值
400，宁拒勿默——写面的归属让给客户端 = 跨租户元数据投毒，投毒的注释/范例
直进 generate_sql 的 prompt）。workspace 暂无断言路径（#8 在册），取服务端
`default_workspace`。datasource 缺省服务端默认源（与召回过滤同源，否则"摄入了
但召回按另一个源过滤"恒不可见）；请求显式选源与 /api/query 同权（P1-3）——
它是目标选择，不是身份。

**网关转发**：agent_server `/sql/train` 改带 `X-Internal-Tenant` 签名头转发
（信任边界 B）；未配 `INTERNAL_HMAC_KEY` 的部署由转发方 503 拒发，不放行
未签名写请求。旧调用方直连本端点须自备身份断言（TENANT_JWT_ENFORCE + JWT，
或内部签名头）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger
from agent_runtime.workspace_registry import server_tenant_id
from fastapi import APIRouter, HTTPException, Request

from nl2sql_service.api.schemas.ingest_schema import IngestReport, IngestRequest
from nl2sql_service.conf.settings import get_settings
from nl2sql_service.services.ingest_service import build_migration_plan, write_scope
from nl2sql_service.services.tenant_scope import TenantScope

logger = get_logger(__name__)

router = APIRouter(prefix="/api/meta", tags=["meta-admin"])


def _as_list(value: str | list[str]) -> list[str]:
    """单串归一为列表（请求体两种形状都收）。"""
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [v for v in value if v and v.strip()]


@router.post("/ingest", response_model=IngestReport)
async def ingest(request: IngestRequest, http_request: Request) -> IngestReport:
    settings = get_settings()
    ctx: Any = getattr(http_request.app.state, "context", None)
    meta_repo = getattr(ctx, "meta_repository", None) if ctx is not None else None
    if meta_repo is None:
        raise HTTPException(status_code=503, detail="meta 库未就绪（META_DB_DSN 未配置？）")

    ddl_texts = _as_list(request.ddl)
    doc_texts = _as_list(request.docs)
    if not (ddl_texts or doc_texts or request.examples):
        raise HTTPException(status_code=400, detail="ddl / docs / examples 至少提供一项")

    # 归属断言（#102）：写端点不接受请求体归属——先拒收显式携带的 scope 字段
    # （宁拒勿默：静默忽略会让"以为写进了 A 租户"的调用方无声写错地方），再要
    # 求服务端断言（无断言 401 fail-fast，不落任何桶）。
    if request.tenant_id or request.workspace_id:
        raise HTTPException(
            status_code=400,
            detail="写入端点不接受请求体归属字段（tenant_id/workspace_id）：作用域一律取服务端断言",
        )
    try:
        tenant = server_tenant_id()
    except ValueError as exc:
        # 身份门未绑定且无部署级 default ⇒ 漏传即抛（_tenant_gate 纪律：不静默落共享桶）
        raise HTTPException(
            status_code=401,
            detail="写入端点需要服务端身份断言（TENANT_JWT_ENFORCE + JWT，或经网关带 X-Internal-Tenant 签名头）",
        ) from exc
    # workspace 暂无断言路径（#8 在册债）：取服务端 default，不采信请求体
    workspace = settings.default_workspace or ""
    scope = TenantScope(tenant_id=tenant, workspace_id=workspace)
    ds_id = request.datasource_id or settings.datasource_id

    # 复用迁移计划（纯函数）：DDL 解析 + 文档关联 + 记账；override 传解析出的
    # 作用域——把本次请求钉在该 scope（计划按行 scope 分组，这里每行同 scope）
    plan = build_migration_plan(
        [{"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id, "content": t} for t in ddl_texts],
        [{"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id, "content": t} for t in doc_texts],
        [
            {"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id, "question": e.question, "sql": e.sql}
            for e in request.examples
        ],
        tenant_override=scope.tenant_id,
        workspace_override=scope.workspace_id,
    )
    scope_plan = plan["scopes"][0] if plan["scopes"] else {"tables": [], "examples": []}

    from nl2sql_service.clients.embedding_client_manager import build_embedder

    embedder = build_embedder(
        settings.embedding_backend,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )
    try:
        stats = await write_scope(
            meta_repo,
            embedder,
            tables=scope_plan["tables"],
            examples=scope_plan["examples"],
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            datasource_id=ds_id,
            vector_dim=settings.vector_dim,
            tokenizer=settings.tokenizer,
        )
    except ValueError as exc:
        # 维度不符等建库前错误：400（调用方喂的数据/配置问题，不是服务端故障）
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "ingest: columns=%s examples=%s scope=[%s/%s/%s] skipped=%d/%d/%d",
        stats["columns"],
        stats["examples"],
        scope.tenant_id,
        scope.workspace_id,
        ds_id,
        len(plan["skipped_ddl"]),
        len(plan["unmapped_docs"]),
        len(plan["skipped_examples"]),
    )
    return IngestReport(
        columns=stats["columns"],
        examples=stats["examples"],
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        datasource_id=ds_id,
        skipped_ddl=plan["skipped_ddl"],
        unmapped_docs=plan["unmapped_docs"],
        skipped_examples=plan["skipped_examples"],
    )
