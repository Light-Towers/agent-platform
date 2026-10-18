"""merge_retrieved_info 节点：RRF 融合多路召回结果 + 表清单派生。

2026-10-18 审计（方案 P0-11③）：
- `rrf_k` 此前硬编码 60，settings 里的 `rrf_k` 是死配置（方案 §5.16-7）；改读 state。
- 库路径下 `state["tables"]` 此前恒空 ⇒ `filter_table` 空转、生成期没有表级视图。
  列级召回本身带 `table_name`（`ColumnRepository.recall` 的 extra_cols），
  这里按列去重派生表清单——不依赖尚不存在的 relations 表。
"""

import json
from typing import Any


def _rrf_fuse(rankings: list[list[dict[str, Any]]], k: int = 60) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            items[key] = item
    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [items[key] for key in sorted_keys]


def _derive_tables(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从列召回结果按 table_name 去重派生表清单（保序）。"""
    seen: list[str] = []
    for col in columns:
        if not isinstance(col, dict):
            continue
        name = col.get("table_name")
        if name and name not in seen:
            seen.append(name)
    return [{"table_name": name} for name in seen]


async def merge_retrieved_info(state: dict[str, Any]) -> dict[str, Any]:
    columns = state.get("columns", [])
    metrics = state.get("metrics", [])
    values = state.get("values", [])

    fused = _rrf_fuse([columns, metrics, values], k=state.get("rrf_k", 60))
    result: dict[str, Any] = {"retrieved_info": json.dumps(fused, ensure_ascii=False)}

    if not state.get("tables"):
        metric_config: dict[str, Any] | None = state.get("metric_config")
        if metric_config is not None:
            tables = list(metric_config.get("tables", []))
        else:
            tables = _derive_tables(columns)
        if tables:
            result["tables"] = tables

    return result
