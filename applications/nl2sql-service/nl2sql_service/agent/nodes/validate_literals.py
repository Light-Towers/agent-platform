"""validate_literals 节点：字面量回字典/探针校验（P0-8②）。

位置在 guard 之后、执行之前：guard 管"语句合法只读"，本节点管"字面量
在不在数据里"。判据只认两种确定性结论：

- **missing**（字典/探针确定不存在）⇒ 拦截，不进 correct 就是白跑一轮
  执行；error_detail 带未命中字面量与该列实际取值建议（前缀建议），
  correct prompt 靠它换一个修复角度；
- **unknown**（探不到：未开 linkable / 分区取不到 / 超时）⇒ **放行**
  ——"探不到"≠"不存在"，拿系统故障拦用户查询是另一种故障（C8）。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.literal_extractor import extract_literals

logger = get_logger(__name__)

#: correct prompt 里的取值建议条数上限（防该列取值很多时撑爆上下文）
_SUGGESTION_LIMIT = 10


async def validate_literals(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    ctx: DataAgentContext | None = state.get("context")
    dialect = state.get("dialect", "postgres")

    probes, has_filter = extract_literals(sql, dialect)
    if not probes or ctx is None or ctx.value_resolver is None:
        # 无字面量/无 resolver：本节点无行为，但要把"带不带维度过滤"留给
        # 零结果分诊用。
        return {"value_matched": [], "value_unmatched": [], "dict_hit": False, "has_dimension_filter": has_filter}

    data_types: dict[str, str] = {}
    for col in state.get("columns", []) or []:
        if isinstance(col, dict) and col.get("table_name") and col.get("column_name"):
            data_types[f"{col['table_name']}.{col['column_name']}"] = col.get("data_type", "")

    resolution = await ctx.value_resolver.resolve(probes, data_types=data_types)
    out: dict[str, Any] = {
        "value_matched": resolution.matched,
        "value_unmatched": resolution.unmatched,
        "dict_hit": resolution.dict_hit,
        "has_dimension_filter": has_filter,
    }
    if resolution.unmatched:
        # 确定性未命中 ⇒ 拦截（correctable：模型大概率能换对字面量）
        suggestions = await _suggestions(ctx, probes, resolution.unmatched)
        logger.info("literal validation failed: unmatched=%s", resolution.unmatched)
        out["error"] = "查询失败：取值未匹配（生成的 SQL 引用了不存在的取值）"
        out["error_class"] = "correctable"
        out["error_detail"] = (
            f"未匹配取值: {', '.join(resolution.unmatched)}"
            + (f"；该列实际取值参考: {', '.join(suggestions)}" if suggestions else "")
        )
    return out


async def _suggestions(ctx: DataAgentContext, probes: list, unmatched: list[str]) -> list[str]:
    """未命中字面量的前缀建议（P0-8③：给别名/前缀建议，允许重生成一次）。"""
    seen: list[str] = []
    for probe in probes:
        if probe.literal not in unmatched or probe.table in seen:
            continue
        seen.append(probe.table)
        values = await ctx.value_resolver.column_values(probe.table, probe.column)
        if not values:
            continue
        prefix_hits = [v for v in values if v.startswith(probe.literal[:1])]
        return (prefix_hits or values)[:_SUGGESTION_LIMIT]
    return []
