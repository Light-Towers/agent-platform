"""recall_value 节点：pgvector 全文 + 向量召回值信息。

入参 metric_config 携带值定义时优先使用，不查预置元知识库。
2026-10-18 审计：此前固定 `embedding=None` ⇒ 向量补位路永远是死的；
现复用 extract_keywords 算好的 `state["query_embedding"]`（P0-11⑤）。
"""

from typing import Any

from nl2sql_service.agent.context import DataAgentContext


async def recall_value(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        values = metric_config.get("values", [])
        return {"values": list(values)}

    keywords = state.get("keywords", [])
    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.value_repository is None:
        return {"values": []}

    # 码表字面检索（P0-5①）：不再走 ANN / 中文全文模糊；自由文本型取值的
    # 模糊匹配由只读探针（P0-9）在源侧完成。embedding 不再下传。
    datasource_id = state.get("datasource_id", "")
    tenant_id = state.get("tenant_id", "")
    workspace_id = state.get("workspace_id", "")
    filters = (("tenant_id", tenant_id), ("workspace_id", workspace_id), ("datasource_id", datasource_id))
    values = await ctx.value_repository.recall(
        keywords,
        top_k=state.get("retrieval_top_k", 10),
        filters=filters,
    )
    return {"values": values}
