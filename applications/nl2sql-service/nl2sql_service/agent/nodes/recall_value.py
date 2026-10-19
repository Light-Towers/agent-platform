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

    try:
        values = await ctx.value_repository.recall(
            keywords,
            embedding=state.get("query_embedding"),
            top_k=state.get("retrieval_top_k", 10),
        )
    except Exception:  # noqa: BLE001 - 召回路 DB 故障降级为空，不阻断查询（#106）
        logger.warning("value recall failed, degraded to empty", exc_info=True)
        values = []
    return {"values": values}
