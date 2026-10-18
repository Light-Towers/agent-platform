"""answer 节点：SQL + 结果 → 人话结论（M0-4 最小形态，§5.11-V3）。

2026-10-18：此前图在 `execute_sql → END` 终结，`query_service` 恒返回空
`answer`（`settings.py:58` "结果由前端 UI 展示"的前提从未兑现）。本节点吃
`sql` + `result` 生成一段结论式回答；明细进 prompt 前按**双上限**截断
（`sql_max_rows_for_prompt` 行 + `sql_prompt_max_bytes` 字节，先到先截），
超过上限的走"汇总统计 + 前 N 行样例"而不是裸截断——模型要答"总数多少"，
裸截断行会给错答案（§5.11-V3-2）。
"""

import json
from typing import Any

from nl2sql_service.agent.llm import LLMClient
from nl2sql_service.agent.nodes._prompt import json_block, load_prompt, render
from nl2sql_service.agent.nodes.generate_sql import build_table_infos

_FALLBACK = "根据查询结果回答：\n{query}\nSQL：{sql}\n结果：\n{result_view}"


def _cell(value: Any) -> Any:
    """JSON 安全化：日期/Decimal 等不可序列化值转字符串。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def summarize_result(
    rows: list[dict[str, Any]] | None,
    *,
    max_rows: int = 100,
    max_bytes: int = 51200,
) -> tuple[str, dict[str, Any]]:
    """结果 → (prompt 文本, 统计)。

    双上限内：全量 JSON。超上限：汇总统计（总行数 + 数值列聚合 + 分布提示）
    + 前 `max_rows` 行样例——汇总值可作答，样例只能举例，两者在文本里分开标注。
    """
    if rows is None:
        return "（无结果）", {"rows": 0, "truncated": False}
    safe = [{k: _cell(v) for k, v in row.items()} for row in rows]
    total = len(safe)
    if total <= max_rows:
        text = json.dumps(safe, ensure_ascii=False)
        if len(text.encode("utf-8")) <= max_bytes:
            return text, {"rows": total, "truncated": False}
    # 超上限：汇总 + 样例
    numeric_cols = [c for c in (safe[0].keys() if safe else []) if all(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool) for r in safe)]
    summary: dict[str, Any] = {"总行数": total, "数值列聚合": {c: round(sum(r[c] for r in safe), 4) for c in numeric_cols}}
    head = f"【汇总统计】{json.dumps(summary, ensure_ascii=False)}\n"
    # 样例按字节上限继续收缩：行数没超但单行极宽时，100 行仍可能超 50KB；
    # 单行就超上限时退到"仅汇总"（`sample = []`），不能死循环。
    sample = safe[:max_rows]
    while sample and len((head + _sample_block(sample)).encode("utf-8")) > max_bytes:
        if len(sample) == 1:
            sample = []
            break
        sample = sample[: len(sample) // 2]
    text = head + _sample_block(sample)
    return text, {"rows": total, "truncated": True, "sample_rows": len(sample), "numeric_cols": numeric_cols}


def _sample_block(sample: list[dict[str, Any]]) -> str:
    if not sample:
        return "【样例行因体量上限全部省略，仅以上方汇总统计作答】"
    return (
        f"【前 {len(sample)} 行样例，仅可用于举例，不可用于回答总量】\n"
        f"{json.dumps(sample, ensure_ascii=False)}"
    )


async def answer(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    result = state.get("result")
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")
    error = state.get("error", "")

    if error:
        # 失败路径不经本节点（图里 fatal/达上限直接 END）；防御性透传
        return {"answer": ""}

    rows = result if isinstance(result, list) else None
    result_view, stats = summarize_result(
        rows,
        max_rows=state.get("sql_max_rows_for_prompt", 100),
        max_bytes=state.get("sql_prompt_max_bytes", 51200),
    )
    if llm is None or not llm.enabled:
        # LLM 不可用时的确定性兜底：结论句 + 结果概要（不许恒空——M0-4 判据）
        head = f"查询成功，共 {stats['rows']} 行。"
        return {"answer": f"{head}\n{result_view}" if rows else head}

    prompt = render(
        load_prompt("answer.prompt", _FALLBACK),
        query=query,
        sql=sql,
        table_infos=build_table_infos(state),
        metric_infos=json_block(state.get("metrics", [])),
        date_info=state.get("date_info", ""),
        db_info=state.get("extra_context") or "PostgreSQL（方言 postgres；只读单条 SELECT）",
        result_view=result_view,
    )
    text = (await llm.invoke(prompt)).strip()
    if not text:
        # LLM 超时/异常降级为空串时，仍要给非空结论（断链时用户看到空回答 = 没答）
        text = f"查询成功，共 {stats['rows']} 行。\n{result_view}"
    return {"answer": text}
