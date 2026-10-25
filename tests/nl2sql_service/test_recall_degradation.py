"""召回节点 DB 故障降级用例（#106）：仓储抛错 ⇒ 降级，不阻断查询。

修复前 recall_column/metric/value/relation 的仓储调用均为裸调用（try/except 只包
embedding）：连接级 statement_timeout、to_tsquery 语法错、库抖动任一异常都直接上抛，
把整请求打成无分类的 internal error——与 docstring"只降级召回路不阻断查询"相悖。

feat 线形态：column/metric 有别名主路（meta_repository.list_aliases →
find_*_by_names），别路失败须回落向量路而非整体失败。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nl2sql_service.agent.nodes.recall_column import recall_column
from nl2sql_service.agent.nodes.recall_metric import recall_metric
from nl2sql_service.agent.nodes.recall_relation import recall_relation
from nl2sql_service.agent.nodes.recall_value import recall_value

_BASE_STATE = {
    "keywords": ["销售额"],
    "context": None,
    "retrieval_top_k": 10,
    "query_embedding": [0.1, 0.2],
    "datasource_id": "dw",
    "tenant_id": "",
    "workspace_id": "",
    "query": "上个月销售额",
}


def _ctx(
    *,
    column_recall: AsyncMock | None = None,
    metric_recall: AsyncMock | None = None,
    value_recall: AsyncMock | None = None,
    list_aliases: AsyncMock | None = None,
    list_relations: AsyncMock | None = None,
    with_meta: bool = False,
) -> MagicMock:
    ctx = MagicMock()
    ctx.column_repository = MagicMock(recall=column_recall or AsyncMock(return_value=[]))
    ctx.metric_repository = MagicMock(recall=metric_recall or AsyncMock(return_value=[]))
    ctx.value_repository = MagicMock(recall=value_recall or AsyncMock(return_value=[]))
    ctx.embedding_client = None
    ctx.meta_repository = (
        MagicMock(list_aliases=list_aliases or AsyncMock(return_value=[]), find_columns_by_names=AsyncMock(return_value=[]), find_metrics_by_names=AsyncMock(return_value=[]))
        if with_meta
        else None
    )
    if list_relations is not None:
        ctx.meta_repository = MagicMock(list_relations=list_relations)
    return ctx


async def test_column_vector_recall_db_error_degrades_to_empty():
    ctx = _ctx(column_recall=AsyncMock(side_effect=RuntimeError("db down")))
    assert await recall_column(dict(_BASE_STATE, context=ctx)) == {"columns": []}


async def test_column_alias_error_falls_back_to_vector():
    """别名路 DB 故障 ⇒ 回落向量路（降级不是失败），向量结果照常返回。"""
    ctx = _ctx(
        column_recall=AsyncMock(return_value=[{"table_name": "orders"}]),
        list_aliases=AsyncMock(side_effect=RuntimeError("db down")),
        with_meta=True,
    )
    assert await recall_column(dict(_BASE_STATE, context=ctx)) == {"columns": [{"table_name": "orders"}]}


async def test_metric_vector_recall_db_error_degrades_to_empty():
    ctx = _ctx(metric_recall=AsyncMock(side_effect=RuntimeError("db down")))
    assert await recall_metric(dict(_BASE_STATE, context=ctx)) == {"metrics": []}


async def test_metric_alias_error_falls_back_to_vector():
    ctx = _ctx(
        metric_recall=AsyncMock(return_value=[{"metric_name": "gmv"}]),
        list_aliases=AsyncMock(side_effect=RuntimeError("db down")),
        with_meta=True,
    )
    assert await recall_metric(dict(_BASE_STATE, context=ctx)) == {"metrics": [{"metric_name": "gmv"}]}


async def test_value_recall_db_error_degrades_to_empty():
    ctx = _ctx(value_recall=AsyncMock(side_effect=RuntimeError("db down")))
    assert await recall_value(dict(_BASE_STATE, context=ctx)) == {"values": []}


async def test_relation_recall_db_error_degrades_to_empty():
    ctx = _ctx(list_relations=AsyncMock(side_effect=RuntimeError("db down")))
    assert await recall_relation(dict(_BASE_STATE, context=ctx)) == {"relations": []}
