"""QueryService：查询服务（组装 12 节点管线执行）。"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class QueryService:
    """查询服务：封装 Text-to-SQL 管线调用。"""

    def __init__(self, graph=None, context=None, llm=None) -> None:
        self._graph = graph
        self._context = context
        self._llm = llm

    def set_graph(self, graph) -> None:
        self._graph = graph

    async def query(self, question: str, **kwargs: Any) -> dict[str, Any]:
        if self._graph is None:
            return {"answer": "", "error": "graph not initialized", "fallback": True}
        state: dict[str, Any] = {"query": question, "context": self._context, "llm": self._llm}
        try:
            result = await self._graph.ainvoke(state)
            return {
                "answer": result.get("answer", ""),
                "sql": result.get("sql", ""),
                "result": result.get("result"),
                "error": result.get("error"),
                "fallback": False,
            }
        except Exception:
            logger.exception("query service failed")
            return {"answer": "", "error": "internal error", "fallback": True}
