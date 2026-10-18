"""生成期上下文接线与执行期错误的回归用例（2026-10-18 审计，方案 P0-11 / S-3 / S-11 邻域）。

钉四件事：
1. 配置面真的进 state（改 settings 能生效，不再恒回落硬编码默认值）；
2. 生成/纠正 prompt 的四个槽来自 state（metric_infos / date_info / 表清单不再恒空）；
3. 查询向量只算一次（三路召回共享）；
4. 执行错误对外分类、原始文本只留在 error_detail；纠正达上限落错误终态而非执行。
"""

from __future__ import annotations

from typing import Any

import pytest
from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.agent.graph import END, _route_after_validate
from nl2sql_service.agent.nodes.execute_sql import classify_error, execute_sql
from nl2sql_service.agent.nodes.generate_sql import generate_sql
from nl2sql_service.agent.nodes.merge_retrieved_info import merge_retrieved_info
from nl2sql_service.agent.nodes.recall_column import recall_column
from nl2sql_service.services.query_service import QueryService, build_date_info


class _StubLLM:
    enabled = True

    def __init__(self) -> None:
        self.prompt: str | None = None

    async def invoke(self, prompt: str) -> str:
        self.prompt = prompt
        return "SELECT 1 LIMIT 1"


class _FakeGraph:
    def __init__(self) -> None:
        self.state: dict[str, Any] | None = None

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.state = state
        return {"sql": "SELECT 1", "error": "", "result": []}


class _BoomEmbedder:
    async def embed_query(self, text: str) -> list[float]:
        raise AssertionError("state 已有 query_embedding 时不应再次调用 embedding")


class _ColumnRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, int]] = []

    async def recall(self, keywords: list[str], embedding: Any = None, top_k: int = 10, **_: Any) -> list[dict]:
        # **_: score_margin/filters 是 2026-10-18 P0-5 新增形参，本用例不关心
        self.calls.append((embedding, top_k))
        return []


class _Dw:
    async def execute_readonly(self, sql: str) -> list[dict]:
        raise RuntimeError("permission denied for table orders")


class _Ctx:
    def __init__(self, dw_repository: Any = None, embedding_client: Any = None, column_repository: Any = None) -> None:
        self.dw_repository = dw_repository
        self.embedding_client = embedding_client
        self.column_repository = column_repository


# --- 配置面接线 -------------------------------------------------------------
async def test_query_service_injects_config_into_state():
    graph = _FakeGraph()
    out = await QueryService(graph=graph, context=None, llm=None).query("统计上个月销售额")

    assert graph.state is not None
    for key in ("sql_max_rows", "sql_max_correct_retries", "retrieval_top_k", "rrf_k", "tokenizer", "date_info"):
        assert key in graph.state, f"state 缺配置键 {key}"
    assert graph.state["date_info"], "date_info 不应为空"
    assert out["fallback"] is False


def test_build_date_info_includes_note():
    class _Settings:
        date_context_note = "数据为 T+1 快照"

    text = build_date_info(_Settings())
    assert "当前时间：" in text
    assert "T+1" in text


# --- 生成期四槽 -------------------------------------------------------------
async def test_generate_sql_uses_state_slots():
    llm = _StubLLM()
    state = {
        "query": "上个月销售额",
        "llm": llm,
        "tables": [{"table_name": "orders"}],
        "columns": [{"table_name": "orders", "column_name": "amount"}],
        "metrics": [{"metric_name": "销售额", "metric_expr": "SUM(amount)"}],
        "values": [],
        "date_info": "当前时间：2026-10-18 09:00 周日（+0800）",
    }
    out = await generate_sql(state)

    assert out["sql"] == "SELECT 1 LIMIT 1"
    assert llm.prompt is not None
    assert "SUM(amount)" in llm.prompt, "指标定义必须进 metric_infos 槽"
    assert "2026-10-18" in llm.prompt, "日期上下文必须进 date_info 槽"
    assert "orders" in llm.prompt, "表清单必须进 table_infos"


# --- 表清单派生 -------------------------------------------------------------
async def test_merge_derives_tables_from_columns():
    out = await merge_retrieved_info(
        {
            "columns": [
                {"table_name": "orders", "column_name": "amount"},
                {"table_name": "venues", "column_name": "name"},
                {"table_name": "orders", "column_name": "created_at"},
            ],
            "metrics": [],
            "values": [],
        }
    )
    assert out["tables"] == [{"table_name": "orders"}, {"table_name": "venues"}]


# --- 检索层：embedding 只算一次 ---------------------------------------------
async def test_recall_column_reuses_query_embedding():
    repo = _ColumnRepo()
    ctx = DataAgentContext(embedding_client=_BoomEmbedder(), column_repository=repo)
    out = await recall_column(
        {"keywords": ["销售额"], "context": ctx, "query_embedding": [0.1, 0.2], "retrieval_top_k": 7}
    )
    assert out["columns"] == []
    assert repo.calls == [([0.1, 0.2], 7)]


# --- 执行期错误分类 ---------------------------------------------------------
def test_classify_error_categories():
    assert classify_error(RuntimeError("permission denied for table orders")) == "查询被拒绝：当前账号无权访问相关数据"
    assert classify_error(RuntimeError('relation "x" does not exist')) == "查询失败：表、字段或语法不正确"
    assert classify_error(RuntimeError("canceling statement due to statement timeout")) == "查询超时：数据量或计算量超出时限"
    assert classify_error(RuntimeError("boom")) == "查询执行失败"


async def test_execute_sql_hides_raw_error():
    out = await execute_sql({"sql": "SELECT 1", "context": _Ctx(dw_repository=_Dw())})
    assert out["error"] == "查询被拒绝：当前账号无权访问相关数据"
    assert "permission denied" in out["error_detail"], "原始错误只留在 error_detail，不进 error"


# --- 路由：达上限落错误终态 -------------------------------------------------
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"sql_valid": True}, "validate_literals"),
        ({"sql_valid": False, "correct_count": 0}, "correct_sql"),
        ({"sql_valid": False, "correct_count": 3, "sql_max_correct_retries": 3}, END),
        ({"sql_valid": False, "correct_count": 1, "sql_max_correct_retries": 1}, END),
    ],
)
def test_route_after_validate(state: dict[str, Any], expected: str):
    assert _route_after_validate(state) == expected
