"""filter_table 节点：LLM 过滤表（白名单交集 + 配置开关 + 异常降级）。

2026-10-19（#109）：`merge_retrieved_info` 的 `_derive_tables` 让本节点由空转变活，
两个后果在此收口：

1. **每请求多一次 LLM 往返** ⇒ 加配置开关（`filter_table_enabled`，默认关：
   不改变复活前的无 LLM 调用行为；派生的表级视图照常进生成期）；
2. **LLM 输出不可直信** ⇒ 只允许在派生清单内**收窄**（白名单交集）：清单外的
   表名（幻觉）、字符串数组、非法 JSON、调用异常，一律回落派生清单——绝不引入
   派生清单之外的表，也不把"空选"当作过滤结果把表清单清空。
"""

import json
from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.llm import LLMClient

logger = get_logger(__name__)


def _picked_names(raw: Any) -> set[str]:
    """LLM 输出 ⇒ 小写表名集合；只认字符串与 {"table_name": ...} 两种形状。"""
    names: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                names.add(item.strip().lower())
            elif isinstance(item, dict):
                name = item.get("table_name")
                if isinstance(name, str):
                    names.add(name.strip().lower())
    return names


async def filter_table(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    tables = state.get("tables", [])
    llm: LLMClient | None = state.get("llm")

    if not tables:
        return {"tables": []}
    if not state.get("filter_table_enabled"):
        return {"tables": tables}  # 开关默认关：不过滤、不产生 LLM 调用
    if llm is None or not llm.enabled:
        return {"tables": tables}

    prompt = f"从候选表中选择回答问题所需的表，输出 JSON 数组：\n问题：{query}\n候选表：{json.dumps(tables, ensure_ascii=False)}"
    try:
        picked = _picked_names(json.loads(await llm.invoke(prompt)))
    except Exception:  # noqa: BLE001 - LLM 解析失败/调用故障 ⇒ 回落派生清单，不阻断查询
        logger.warning("filter_table llm output unusable, fallback to derived tables", exc_info=True)
        return {"tables": tables}
    if not picked:
        return {"tables": tables}  # 空选视为无效输出（不把"空"当过滤结果）
    derived = [
        t
        for t in tables
        if isinstance(t, dict) and str(t.get("table_name", "")).strip().lower() in picked
    ]
    return {"tables": derived or tables}
