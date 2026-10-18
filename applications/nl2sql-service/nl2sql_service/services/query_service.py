"""QueryService：查询服务（组装 12 节点管线执行）。

2026-10-18 审计（方案 §5.11-V2 / §5.16-7）：配置面集中在这里注入 state。
此前 `sql_max_rows`/`sql_max_correct_retries`/`retrieval_top_k`/`rrf_k`/`tokenizer`
都只有定义没有消费者，节点 `state.get(..., 默认)` 恒回落硬编码值——改配置不生效。
"""

from datetime import datetime, timezone
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def build_date_info(settings: Any) -> str:
    """生成期日期上下文（P0-11①）：系统日期 + 可选数据口径说明。

    "上个月/今年/最近 7 天"的锚点是**当前日期**，而数据本身可能是 T+1 快照，
    两者不是一回事——`date_context_note` 让部署方声明后者，不写死在代码里。
    """
    now = datetime.now(timezone.utc).astimezone()
    stamp = f"{now:%Y-%m-%d %H:%M} {_WEEKDAYS[now.weekday()]}（{now:%z}）"
    note = getattr(settings, "date_context_note", "") or ""
    return f"当前时间：{stamp}" + (f"；口径说明：{note}" if note else "")


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

        from nl2sql_service.conf.settings import get_settings

        settings = get_settings()
        metric_config = kwargs.get("metric_config")
        state: dict[str, Any] = {
            "query": question,
            "context": self._context,
            "llm": self._llm,
            "sql_max_rows": settings.sql_max_rows,
            "sql_max_correct_retries": settings.sql_max_correct_retries,
            "retrieval_top_k": settings.retrieval_top_k,
            "rrf_k": settings.rrf_k,
            "tokenizer": settings.tokenizer,
            "date_info": build_date_info(settings),
        }
        if metric_config is not None:
            state["metric_config"] = (
                metric_config.to_recall_result()
                if hasattr(metric_config, "to_recall_result")
                else metric_config
            )
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
