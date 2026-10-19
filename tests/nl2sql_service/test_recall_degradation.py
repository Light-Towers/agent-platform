"""三路召回的 DB 故障降级用例（#106）：repository.recall 抛错 ⇒ 空列表，不阻断查询。

修复前三个节点的 repository.recall() 均为裸调用（try/except 只包 embedding）：
连接级 statement_timeout、to_tsquery 语法错、向量路由激活任一异常都直接上抛，
把整请求打成无分类的 internal error——与 docstring"只降级召回路不阻断查询"相悖。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nl2sql_service.agent.nodes.recall_column import recall_column
from nl2sql_service.agent.nodes.recall_metric import recall_metric
from nl2sql_service.agent.nodes.recall_value import recall_value


def _ctx_with_broken_repo() -> MagicMock:
    ctx = MagicMock()
    ctx.column_repository = MagicMock(recall=AsyncMock(side_effect=RuntimeError("db down")))
    ctx.metric_repository = MagicMock(recall=AsyncMock(side_effect=RuntimeError("db down")))
    ctx.value_repository = MagicMock(recall=AsyncMock(side_effect=RuntimeError("db down")))
    ctx.embedding_client = None
    return ctx


_BASE_STATE = {
    "keywords": ["订单"],
    "context": None,
    "retrieval_top_k": 10,
    "query_embedding": [0.1, 0.2],
}


async def test_column_recall_db_error_degrades_to_empty():
    state = dict(_BASE_STATE, context=_ctx_with_broken_repo())
    assert await recall_column(state) == {"columns": []}


async def test_metric_recall_db_error_degrades_to_empty():
    state = dict(_BASE_STATE, context=_ctx_with_broken_repo())
    assert await recall_metric(state) == {"metrics": []}


async def test_value_recall_db_error_degrades_to_empty():
    state = dict(_BASE_STATE, context=_ctx_with_broken_repo())
    assert await recall_value(state) == {"values": []}
