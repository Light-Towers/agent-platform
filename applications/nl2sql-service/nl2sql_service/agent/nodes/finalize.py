"""finalize 节点：终态持久化（§5.13 M2/M6 会话四元组 + P0-4/H4 查询追溯）。

位置在 answer 之后、END 之前：这一轮的结果已经齐了，在此把**下一次继承要用的
四元组**与**这次问答的 trace 行**落库。两块持久化都在这里，是因为它们消费同一份
终态数据、且都该在"答案已出"后做（trace 要记最终 SQL 与最终结果行数）。

- **会话四元组（M2/M6）**：只存四元组 + 已确认问答对，不存 retrieved_info 大文本。
  confirmed_pairs **不自动增长**——M6 要求"人不确认的（错题）不进范例库"，
  本管线无人工确认环，故只透传上游已确认的对（当前恒等于不新增），把"确认"
  留给未来人工修订入口，避免把未确认口径固化成范例。
- **查询追溯（H4）**：每次问答一行，含召回四件套、matched/unmatched、llm_calls、
  latency、meta_revision 等——golden 回归与未命中字面量日报的数据源。字段对齐
  OTel GenAI 语义约定（G2：不自造 trace 方言）。

**不因持久化失败而fail请求**：trace/session 写库是旁路，失败只记日志——答案
已经产出并返回给用户，不能因为"记一笔账"失败就把成功查询打成失败。
"""

from __future__ import annotations

import time
from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.query_rewriter import extract_time_window

logger = get_logger(__name__)


def build_quadruple(state: dict[str, Any]) -> dict[str, Any]:
    """本轮终态 → 下一轮继承四元组（M2）。

    - time_window：从原始 query 抽显式年月（best-effort，抽不到留空）；
    - entities：已确认取值（value_matched）+ 召回表名——下一轮"上述"的承接对象；
    - candidate_tables：本轮候选表；
    - generated_sql：本轮最终 SQL（下一轮"改成按周统计"类的改写基线）。
    """
    entities = list(state.get("value_matched") or [])
    for t in state.get("tables") or []:
        name = t.get("table_name") if isinstance(t, dict) else None
        if name and name not in entities:
            entities.append(name)
    candidate_tables = [
        t.get("table_name") for t in (state.get("tables") or []) if isinstance(t, dict) and t.get("table_name")
    ]
    return {
        "time_window": extract_time_window(state.get("query", "")),
        "entities": entities,
        "candidate_tables": candidate_tables,
        "generated_sql": state.get("sql", ""),
    }


def build_trace(state: dict[str, Any], latency_ms: float) -> dict[str, Any]:
    """本轮终态 → nl2sql_query_trace 行（H4/G2）。"""
    result = state.get("result")
    rows = len(result) if isinstance(result, list) else 0
    return {
        "session_id": state.get("session_id", ""),
        "datasource_id": state.get("datasource_id", ""),
        "turn": int(state.get("turn") or 0),
        "query": state.get("query", ""),
        "rewritten_query": state.get("effective_query", ""),
        "sql": state.get("sql", ""),
        "error": state.get("error", ""),
        "error_class": state.get("error_class", ""),
        "error_detail": state.get("error_detail", ""),
        "recalled_tables": [t.get("table_name") for t in (state.get("tables") or []) if isinstance(t, dict)],
        "recalled_columns": [c.get("column_name") for c in (state.get("columns") or []) if isinstance(c, dict)],
        "recalled_metrics": [m.get("metric_name") for m in (state.get("metrics") or []) if isinstance(m, dict)],
        "recalled_values": list(state.get("value_matched") or []),
        "matched_values": list(state.get("value_matched") or []),
        "unmatched_terms": list(state.get("value_unmatched") or []),
        "dict_hit": bool(state.get("dict_hit", False)),
        "llm_calls": int(state.get("llm_calls") or 0),
        "embedding_calls": 0,
        "latency_ms": latency_ms,
        "meta_revision": 0,
        "source_snapshot": "",
        "model": "",
        "prompt_version": "",
        "result_rows": rows,
        "empty_result": bool(state.get("empty_result", False)),
        "path": state.get("path", "graph"),
    }


async def finalize(state: dict[str, Any]) -> dict[str, Any]:
    """终态持久化：trace 恒写（有 meta 库时），会话四元组仅在有 session_id 时写。"""
    ctx: DataAgentContext | None = state.get("context")
    meta = getattr(ctx, "meta_repository", None) if ctx is not None else None
    if meta is None:
        return {}

    # latency：节点层无请求起点，用 state 里 QueryService 注入的起点（无则 0）
    start = state.get("_start_perf")
    latency_ms = (time.perf_counter() - start) * 1000 if start else 0.0

    try:
        await meta.insert_trace(build_trace(state, latency_ms))
    except Exception:  # noqa: BLE001 - 记账失败不fail已产出的答案
        logger.info("trace insert failed（002 未应用？）", exc_info=True)

    session_id = (state.get("session_id") or "").strip()
    if session_id:
        try:
            prev = state.get("inherit_quadruple") or {}
            confirmed = prev.get("confirmed_pairs") if isinstance(prev, dict) else None
            await meta.upsert_session(
                session_id=session_id,
                datasource_id=state.get("datasource_id", ""),
                quadruple=build_quadruple(state),
                confirmed_pairs=confirmed if isinstance(confirmed, list) else [],
                turn=int(state.get("turn") or 1),
            )
        except Exception:  # noqa: BLE001 - 同上，旁路失败不fail请求
            logger.info("session upsert failed", exc_info=True)
    return {}
