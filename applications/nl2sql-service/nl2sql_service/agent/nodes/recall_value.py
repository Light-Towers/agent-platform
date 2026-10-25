"""recall_value 节点：pgvector 全文 + 向量召回值信息。

入参 metric_config 携带值定义时优先使用，不查预置元知识库。
2026-10-18 审计：此前固定 `embedding=None` ⇒ 向量补位路永远是死的；
现复用 extract_keywords 算好的 `state["query_embedding"]`（P0-11⑤）。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext

logger = get_logger(__name__)


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
    # D8 摘键（006）：元知识全企业共享，workspace 不再参与召回过滤
    filters = (("tenant_id", tenant_id), ("datasource_id", datasource_id))
    try:
        values = await ctx.value_repository.recall(
            keywords,
            top_k=state.get("retrieval_top_k", 10),
            filters=filters,
        )
    except Exception:  # noqa: BLE001 - 取值路 DB 故障降级空召回，不阻断查询（#106）
        logger.warning("value recall failed, degraded to empty", exc_info=True)
        values = []
    return {"values": values}
