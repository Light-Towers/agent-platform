"""recall_metric 节点：别名精确匹配主路 + pgvector 向量召回指标信息。

入参 metric_config 携带指标定义时优先使用，不查预置元知识库。
embedding 由 extract_keywords 统一计算后经 `state["query_embedding"]` 传入
（2026-10-18 审计 P0-11⑤）。

2026-10-18（P0-5 主路落地）：别名精确匹配优先于向量——问"上个月 GMV"
应直接命中声明 `销售额 → GMV` 的指标定义，而不是靠稠密向量撞运气。
"""

from typing import Any

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.alias_matcher import match_aliases


async def recall_metric(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        metrics = metric_config.get("metrics", [])
        return {"metrics": list(metrics)}

    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.metric_repository is None:
        return {"metrics": []}

    datasource_id = state.get("datasource_id", "")
    if ctx.meta_repository is not None:
        aliases = await ctx.meta_repository.list_aliases(datasource_id)
        hits = match_aliases(state.get("query", ""), keywords, aliases, "metric")
        if hits:
            rows = await ctx.meta_repository.find_metrics_by_names(hits, datasource_id)
            if rows:
                return {"metrics": rows}

    embedding: list[float] | None = state.get("query_embedding")
    if embedding is None and ctx.embedding_client is not None:
        try:
            embedding = await ctx.embedding_client.embed_query(" ".join(keywords))
        except Exception:  # noqa: BLE001 - 向量化失败降级为空召回，不阻断查询
            embedding = None

    metrics = await ctx.metric_repository.recall(
        keywords, embedding=embedding, top_k=state.get("retrieval_top_k", 10)
    )
    return {"metrics": metrics}
