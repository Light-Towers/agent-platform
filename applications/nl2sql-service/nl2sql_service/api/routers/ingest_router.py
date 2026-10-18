"""POST /api/meta/ingest：训练数据在线摄入（A 方案 Stage ③，替代 agent_server /sql/train）。

**为什么需要**：agent_server 的 `/sql/train`（DDL/文档/范例即时进库）是上线端点
（2026-10-12 release runbook 有记录），agent_server/sql 退役后这条路不能断——
本端点用**同一套写入 core**（`services/ingest_service.write_scope`，与迁移 CLI
共用）把它接过来：DDL→column_info、文档→table_comment、范例→example_info。

**与迁移 CLI 的分工**：CLI 批量搬历史数据（读源库三表、多 scope、--prune）；
本端点管在线增量（一次一个作用域、不 prune——范例的差异删是显式运维动作，
不该被一次摄入顺带删掉）。

**隔离**：tenant 按 ADR-0007 服务端断言 > 请求体 > default_tenant（同 /api/query
的 `resolve_scope`）；datasource 缺省服务端默认源（与召回过滤同源，否则"摄入了
但召回按另一个源过滤"恒不可见）。

**未接身份门（S-1）下的定位**：与 /api/meta/refresh 同級——登记为内部/运维端点，
接入身份门后加 admin 断言。写操作的最坏后果是往元知识库加/改行（可 prune/重灌
恢复），且三类记账全部回传（喂坏了看得见）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger
from fastapi import APIRouter, HTTPException, Request

from nl2sql_service.api.schemas.ingest_schema import IngestReport, IngestRequest
from nl2sql_service.conf.settings import get_settings
from nl2sql_service.services.ingest_service import build_migration_plan, write_scope
from nl2sql_service.services.tenant_scope import resolve_scope

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

    # 隔离作用域（P1-1 / ADR-0007）：服务端断言 > 请求体 > default
    scope = resolve_scope(
        request_tenant=request.tenant_id,
        request_workspace=request.workspace_id,
        default_tenant=settings.default_tenant,
        default_workspace=settings.default_workspace,
    )
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
