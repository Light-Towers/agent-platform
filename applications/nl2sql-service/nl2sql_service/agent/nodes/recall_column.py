"""recall_column 节点：别名精确匹配主路 + pgvector 向量召回列信息。

入参 metric_config 携带列定义时优先使用，不查预置元知识库。
embedding 由 extract_keywords 统一计算后经 `state["query_embedding"]` 传入
（2026-10-18 审计 P0-11⑤）；仅在直接调节点、state 缺该键时才自行计算。

2026-10-18（P0-5 主路落地）：别名精确匹配**优先于**向量——"GMV→销售额"
这类口语变体靠向量撞运气，等值查找才准。命中别名即取目标列行返回，
不再走 ANN；未命中才回落向量路。
"""

from typing import Any

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.alias_matcher import match_aliases


async def recall_column(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        columns = metric_config.get("columns", [])
        return {"columns": list(columns)}

    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.column_repository is None:
        return {"columns": []}

    # 主路：别名精确匹配（meta 库有别名表时才走）
    datasource_id = state.get("datasource_id", "")
    tenant_id = state.get("tenant_id", "")
    workspace_id = state.get("workspace_id", "")
    if ctx.meta_repository is not None:
        aliases = await ctx.meta_repository.list_aliases(datasource_id, tenant_id=tenant_id, workspace_id=workspace_id)
        hits = match_aliases(state.get("query", ""), keywords, aliases, "column")
        if hits:
            rows = await ctx.meta_repository.find_columns_by_names(
                hits, datasource_id, tenant_id=tenant_id, workspace_id=workspace_id
            )
            if rows:
                return {"columns": rows}

    embedding: list[float] | None = state.get("query_embedding")
    if embedding is None and ctx.embedding_client is not None:
        try:
            embedding = await ctx.embedding_client.embed_query(" ".join(keywords))
        except Exception:  # noqa: BLE001 - 向量化失败降级为空召回，不阻断查询
            embedding = None

    # 作用域过滤（P1-1 隔离）：tenant/workspace/datasource 三列恒过滤——空值匹配
    # DDL 默认 '' 行（单租户 dev 向后兼容），非空则隔离到该作用域（禁跨租户召回）。
    filters = (("tenant_id", tenant_id), ("workspace_id", workspace_id), ("datasource_id", datasource_id))
    columns = await ctx.column_repository.recall(
        keywords,
        embedding=embedding,
        top_k=state.get("retrieval_top_k", 10),
        score_margin=state.get("retrieval_score_margin", 0.0),
        filters=filters,
    )
    return {"columns": columns}
