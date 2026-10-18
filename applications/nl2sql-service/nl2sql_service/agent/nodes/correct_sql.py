"""correct_sql 节点：LLM 纠正循环，加载 prompts/correct_sql.prompt。

2026-10-18 审计（方案 P0-11④）：纠正轮上下文不得少于生成轮——此前
`table_infos` 只有融合文本、`metric_infos`/`date_info` 恒空串、表清单缺失。

2026-10-18（方案 §5.11-E2 实装）：执行期异常也进本节点，两处契约：
1. prompt 的 error 槽喂 **error_detail（DB 原文）**——对外分类消息
   （"查询失败：表、字段或语法不正确"）对修 SQL 没有任何信息量；
2. prompt 必须带 **attempted_sql**（已尝试的 SQL + 错误序列）——没有它，
   模型会把同一处错改三遍（§5.11 feedback 契约③）。
"""

from typing import Any

from nl2sql_service.agent.llm import LLMClient
from nl2sql_service.agent.nodes._prompt import json_block, load_prompt, render
from nl2sql_service.agent.nodes.generate_sql import build_db_info, build_relations_block, build_table_infos

_FALLBACK = "纠正以下 SQL：\n{sql}\n错误：{error}\n已尝试：\n{attempted_sql}"


def build_attempted_block(attempted: list[dict[str, Any]] | None) -> str:
    """已尝试序列 → prompt 文本；空历史给显式占位而不是空串。"""
    if not attempted:
        return "（无历史尝试）"
    lines = []
    for i, item in enumerate(attempted, start=1):
        lines.append(f"- 第 {i} 次尝试的 SQL：{item.get('sql', '')}\n  错误：{item.get('error', '')}")
    return "\n".join(lines)


async def correct_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    error = state.get("error", "")
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")
    correct_count = state.get("correct_count", 0)

    if llm is None or not llm.enabled:
        return {"sql": sql, "error": error, "correct_count": correct_count + 1}

    if correct_count >= state.get("sql_max_correct_retries", 3):
        return {"sql": sql, "error": "纠正次数已达上限"}

    prompt = render(
        load_prompt("correct_sql.prompt", _FALLBACK),
        query=query,
        table_infos=build_table_infos(state),
        metric_infos=json_block(state.get("metrics", [])),
        date_info=state.get("date_info", ""),
        db_info=build_db_info(state),
        sql=sql,
        # DB 原文才进 prompt（对外分类消息无修正信息量）；guard 拒绝轮没有
        # error_detail，回落 error。
        error=state.get("error_detail") or error,
        attempted_sql=build_attempted_block(state.get("attempted_sql")),
        # 关系声明与生成轮同源（P0-11④：纠正轮上下文不少于生成轮）
        relations=build_relations_block(state.get("relations")),
    )
    corrected = await llm.invoke(prompt)
    # error_detail 一并清空：它是"本轮执行的原始错误"，纠正后已过期
    return {"sql": corrected, "error": "", "error_detail": "", "correct_count": correct_count + 1}
