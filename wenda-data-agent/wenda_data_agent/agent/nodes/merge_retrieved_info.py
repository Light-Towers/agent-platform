"""merge_retrieved_info 节点：RRF 融合多路召回结果。"""

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


async def merge_retrieved_info(state: dict[str, Any]) -> dict[str, Any]:
    columns = state.get("columns", [])
    metrics = state.get("metrics", [])
    values = state.get("values", [])

    fused = _rrf_fuse([columns, metrics, values], k=60)
    retrieved_info = json.dumps(fused, ensure_ascii=False)
    return {"retrieved_info": retrieved_info}
