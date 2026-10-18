"""recall_relation 节点：表间关系召回（§5.14-R3）。

入参 metric_config 携带关系声明时优先使用；否则读 meta 库的冻结关系集
（R5：查询路径只读、服务期零人工、无确认弹窗）。
"""

from typing import Any

from nl2sql_service.agent.context import DataAgentContext


async def recall_relation(state: dict[str, Any]) -> dict[str, Any]:
    metric_config: dict[str, Any] | None = state.get("metric_config")
    if metric_config is not None:
        return {"relations": list(metric_config.get("relations", []))}

    ctx: DataAgentContext | None = state.get("context")
    if ctx is None or ctx.meta_repository is None:
        return {"relations": []}

    datasource_id = state.get("datasource_id", "")
    relations = await ctx.meta_repository.list_relations(datasource_id)
    return {"relations": relations}
