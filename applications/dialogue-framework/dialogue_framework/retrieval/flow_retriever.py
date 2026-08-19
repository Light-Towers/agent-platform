"""FlowRetriever：Flow 检索（从已加载 Flow 定义中召回相关 Flow）。"""

from typing import Any


class FlowRetriever:
    def __init__(self, flows: dict[str, Any]) -> None:
        self._flows = flows

    async def retrieve(self, query: str, k: int = 4) -> list[dict]:
        """按关键词简单匹配 Flow id/描述；生产可替换为向量召回。"""
        results = []
        query_lower = query.lower()
        for fid, flow in self._flows.items():
            text = f"{fid} {flow.get('description', '')}".lower()
            if any(w in text for w in query_lower.split()):
                results.append({"flow_id": fid, "score": 1.0})
        return results[:k]
