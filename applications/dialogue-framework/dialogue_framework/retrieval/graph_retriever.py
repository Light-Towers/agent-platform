"""GraphRetriever：Neo4j 图检索可插拔接口抽象。

接口抽象 + pgvector 关系建模生产占位 + Neo4j 课程实现可切换（不引入 neo4j 运行时依赖）。
GRAPH_BACKEND 环境变量切换；Neo4j 未配置时降级 pgvector 占位。
"""

from dataclasses import dataclass
from typing import Any

from dialogue_framework.shared.config import get_settings


@dataclass
class GraphResult:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class GraphRetriever:
    """图检索统一入口，按 GRAPH_BACKEND 切换实现。"""

    def __init__(self) -> None:
        self._backend = get_settings().graph_backend

    async def graph_query(self, query: str) -> GraphResult:
        if self._backend == "neo4j":
            return await self._query_neo4j(query)
        return await self._query_pgvector(query)

    async def _query_pgvector(self, query: str) -> GraphResult:
        """生产占位：pgvector 关系建模待实现，返回空结果。"""
        return GraphResult(nodes=[], edges=[])

    async def _query_neo4j(self, query: str) -> GraphResult:
        """课程实现可切换：需本地 Neo4j，不引入运行时依赖。

        未配置时降级 pgvector 占位。
        """
        return await self._query_pgvector(query)
