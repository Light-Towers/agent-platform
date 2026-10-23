"""recall_metric 节点：别名精确匹配主路 + pgvector 向量召回指标信息。

入参 metric_config 携带指标定义时优先使用，不查预置元知识库。
embedding 由 extract_keywords 统一计算后经 `state["query_embedding"]` 传入
（2026-10-18 审计 P0-11⑤）。

2026-10-18（P0-5 主路落地）：别名精确匹配优先于向量——问"上个月 GMV"
应直接命中声明 `销售额 → GMV` 的指标定义，而不是靠稠密向量撞运气。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.alias_matcher import match_aliases

logger = get_logger(__name__)


async def recall_metric(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        metrics = metric_config.get("metrics", [])
        return {"metrics": list(metrics)}

    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.metric_repository is None:
        return {"metrics": []}

    # 主路：别名精确匹配。DB 故障一律降级（#106）：别名路回落向量路、
    # 向量路降级空召回，不阻断查询。
    datasource_id = state.get("datasource_id", "")
    tenant_id = state.get("tenant_id", "")
    if ctx.meta_repository is not None:
        try:
            aliases = await ctx.meta_repository.list_aliases(datasource_id, tenant_id=tenant_id, workspace_id=state.get("workspace_id", ""))
            hits = match_aliases(state.get("query", ""), keywords, aliases, "metric")
            if hits:
                rows = await ctx.meta_repository.find_metrics_by_names(
                    hits, datasource_id, tenant_id=tenant_id, workspace_id=state.get("workspace_id", "")
                )
                if rows:
                    return {"metrics": rows}
        except Exception:  # noqa: BLE001 - 别名路 DB 故障回落向量路，不阻断查询
            logger.warning("metric alias recall failed, falling back to vector", exc_info=True)

    embedding: list[float] | None = state.get("query_embedding")
    if embedding is None and ctx.embedding_client is not None:
        try:
            embedding = await ctx.embedding_client.embed_query(" ".join(keywords))
        except Exception:  # noqa: BLE001 - 向量化失败降级为空召回，不阻断查询
            embedding = None

    # D8 摘键（006）：元知识全企业共享，workspace 不再参与召回过滤
    filters = (("tenant_id", tenant_id), ("datasource_id", datasource_id))
    try:
        metrics = await ctx.metric_repository.recall(
            keywords,
            embedding=embedding,
            top_k=state.get("retrieval_top_k", 10),
            score_margin=state.get("retrieval_score_margin", 0.0),
            filters=filters,
        )
    except Exception:  # noqa: BLE001 - 向量路 DB 故障降级空召回，不阻断查询（#106）
        logger.warning("metric recall failed, degraded to empty", exc_info=True)
        metrics = []
    return {"metrics": metrics}
