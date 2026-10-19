"""recall_relation 节点：表间关系召回（§5.14-R3）。

入参 metric_config 携带关系声明时优先使用；否则读 meta 库的冻结关系集
（R5：查询路径只读、服务期零人工、无确认弹窗）。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext

logger = get_logger(__name__)


async def recall_relation(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        return {"relations": list(metric_config.get("relations", []))}

    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.meta_repository is None:
        return {"relations": []}

    datasource_id = state.get("datasource_id", "")
    tenant_id = state.get("tenant_id", "")
    workspace_id = state.get("workspace_id", "")
    try:
        relations = await ctx.meta_repository.list_relations(
            datasource_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
    except Exception:  # noqa: BLE001 - 关系路 DB 故障降级空召回，不阻断查询（#106）
        logger.warning("relation recall failed, degraded to empty", exc_info=True)
        relations = []
    return {"relations": relations}
