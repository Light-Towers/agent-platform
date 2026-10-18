"""triage_empty 节点：零结果分诊（P0-8③）。

查询成功但 0 行时，区分两种完全不同的情况：

1. **取值未匹配**：维度过滤里的字面量在源侧不存在 ⇒ 明确回答"未识别取值"
   （给实际取值建议），并允许进 correct 重生成一次——**不返回 0、不静默
   用错值**（P0-8③ 行内纪律）；
2. **该条件下真无数据**：如实说"没有符合条件的数据"，不硬造答案。

探不到的列（unknown）按 2 处理——拿系统故障说成"未识别取值"是误判。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.literal_extractor import extract_literals

logger = get_logger(__name__)


async def triage_empty(state: dict[str, Any]) -> dict[str, Any]:
    result = state.get("result")
    rows = result if isinstance(result, list) else []
    out: dict[str, Any] = {"empty_result": not rows}
    if rows:
        return out

    ctx: DataAgentContext | None = state.get("context")
    sql = state.get("sql", "")
    probes, has_filter = extract_literals(sql, state.get("dialect", "postgres"))
    if not has_filter or not probes or ctx is None or ctx.value_resolver is None:
        out["empty_result_reason"] = "no_dimension_filter" if not has_filter else "no_resolver"
        return out

    resolution = await ctx.value_resolver.resolve(probes)
    if resolution.unmatched:
        # 确定性未命中 ⇒ 这是"取值未匹配"，不是"无数据"
        out["empty_result_reason"] = "unrecognized_literal"
        out["error"] = "查询结果为空：取值未匹配"
        out["error_class"] = "correctable"
        out["error_detail"] = (
            f"未匹配取值: {', '.join(resolution.unmatched)}"
            "（零结果分诊：该取值在源侧不存在，不是'无数据'）"
        )
        logger.info("empty-result triage: unrecognized literal %s", resolution.unmatched)
        return out
    out["empty_result_reason"] = "genuinely_empty"
    return out
