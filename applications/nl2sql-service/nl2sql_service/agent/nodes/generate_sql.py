"""generate_sql 节点：LLM 生成 SQL，加载 prompts/generate_sql.prompt。

2026-10-18 审计（方案 P0-11）：四个槽必须来自 state，而不是恒空串——
`metric_infos` 此前固定 `""`（指标口径白召回）、`date_info` 固定 `""`（相对时间无锚点）、
`table_infos` 只有 RRF 混合 JSON（没有表级视图）。
"""

import json
from typing import Any

from nl2sql_service.agent.llm import LLMClient
from nl2sql_service.agent.nodes._prompt import json_block, load_prompt, render
from nl2sql_service.services.prompt_sanitizer import (
    COLUMN_FREE_FIELDS,
    METRIC_FREE_FIELDS,
    TABLE_FREE_FIELDS,
    sanitize_free_text,
    sanitize_meta,
)

_FALLBACK = "根据以下信息生成 SQL：\n{query}\n表信息：{table_infos}\n指标信息：{metric_infos}\n表间关系：{relations}\n{aggregation_hint}"


def build_relations_block(relations: list[dict[str, Any]] | None) -> str:
    """关系声明 → prompt 文本（§5.14-R3：相关 JOIN 条件显式注入）。

    没有声明时给显式占位——"无声明"与"忘了传"在 prompt 里必须可区分，
    否则 LLM 会把缺声明当成可以随便猜 JOIN 的许可。
    """
    if not relations:
        return "（无关系声明：不得凭同名列猜测 JOIN 关系）"
    lines = []
    for rel in relations:
        # S-8：关系 note 是自由文本（消歧说明），同样过清洗
        note_raw = sanitize_free_text(rel.get("note", ""))
        note = f"（{note_raw}）" if note_raw else ""
        lines.append(
            f"- {rel.get('left_table', '')}.{rel.get('left_column', '')} "
            f"{rel.get('relation_type', 'many_to_one')} → "
            f"{rel.get('right_table', '')}.{rel.get('right_column', '')}{note}"
        )
    return "\n".join(lines)


def build_aggregation_hint(state: dict[str, Any], threshold: int = 1_000_000) -> str:
    """聚合引导（§5.11-V3-3）：候选表行数估值超阈值时提示优先聚合。

    估值来自漂移检测的表统计（P0-3，QueryService 注入 `table_stats`）；
    无估值返回空串——不猜、不硬编码"表很大"。
    """
    stats = state.get("table_stats") or []
    big = [s.get("table_name", "") for s in stats if isinstance(s, dict) and (s.get("row_estimate") or 0) >= threshold]
    if not big:
        return ""
    return (
        "注意：以下候选表行数估值极大（"
        + "、".join(big)
        + "）。若问题关心的是总量/均值/计数等汇总语义，必须使用聚合函数（SUM/COUNT/AVG）"
        "而非返回明细行；确需明细时必须带有效的过滤条件与 LIMIT。"
    )


def build_table_infos(state: dict[str, Any]) -> str:
    """生成期表上下文：表 / 列 / 取值分块。

    优先用 state 里各自的结构化列表；三者全空时回落到 merge 节点产出的
    融合文本（无元知识的降级路径）。
    """
    tables = state.get("tables", [])
    columns = state.get("columns", [])
    values = state.get("values", [])
    if not (tables or columns or values):
        return state.get("retrieved_info", "")
    # S-8 二阶注入防御：自由文本（表/列注释）进 prompt 前统一清洗——
    # 折叠换行防伪造分节、指令特征过滤、长度截断。标识符字段不动。
    tables = sanitize_meta(tables, TABLE_FREE_FIELDS)
    columns = sanitize_meta(columns, COLUMN_FREE_FIELDS)
    return (
        f"【表】{json_block(tables)}\n"
        f"【列】{json_block(columns)}\n"
        f"【取值】{build_value_bindings(values)}"
    )


def build_value_bindings(values: list[dict[str, Any]] | None) -> str:
    """取值结构化绑定（P0-8①）：`[{column, value, desc}, ...]`。

    不再是自由文本 `examples`——绑定是给模型"只能用这些字面量"的契约，
    形状统一才能被下游（字面量核验、matched/unmatched 回传）复用。
    """
    if not values:
        return "（无已声明取值）"
    # S-8：value_desc 是自由文本，同样过清洗（与表/列注释同源同威胁）
    bindings = [
        {
            "column": v.get("column_name", ""),
            "value": v.get("value", ""),
            "desc": sanitize_free_text(v.get("value_desc", "")),
        }
        for v in values
        if isinstance(v, dict)
    ]
    return json.dumps(bindings, ensure_ascii=False)


def build_db_info(state: dict[str, Any]) -> str:
    """数据源方言说明（P1-4）：生成期就让模型知道目标方言与源专有语法边界。

    extra_context（add_extra_context 注入的 dialect+version）优先；缺省按
    state.dialect 给一句方言约束——把 `WITH PARSER ngram`（MySQL）/ `MATCH_ANY`
    （Doris）这类不可互发的语法在**生成期**就点明，而不是运行时报错兜底。
    """
    extra = state.get("extra_context") or ""
    if extra:
        return extra
    dialect = state.get("dialect") or "postgres"
    return f"{dialect}（方言 {dialect}；只输出单条只读 SELECT）"


async def generate_sql(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")

    if llm is None or not llm.enabled:
        return {"sql": "", "error": "LLM not configured"}

    prompt = render(
        load_prompt("generate_sql.prompt", _FALLBACK),
        query=query,
        table_infos=build_table_infos(state),
        metric_infos=json_block(sanitize_meta(state.get("metrics", []), METRIC_FREE_FIELDS)),
        date_info=state.get("date_info", ""),
        db_info=build_db_info(state),
        aggregation_hint=build_aggregation_hint(state),
        relations=build_relations_block(state.get("relations")),
    )
    sql = await llm.invoke(prompt)
    return {"sql": sql, "error": "", "llm_calls": state.get("llm_calls", 0) + 1}
