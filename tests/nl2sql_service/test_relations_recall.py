"""关系召回与别名精确匹配用例（2026-10-18，§5.14-R3/R4/R5 + P0-5 主路）。

钉六件事：
1. 别名精确匹配**优先于**向量：问"上个月 GMV"命中声明 `销售额 → GMV`
   的指标定义（无声明时维持撞运气现状，不退化）；
2. 机提别名（source=machine）不参与召回（§5.14-R1）；
3. recall_relation 读 meta 库冻结关系集（R5：服务期只读、零人工）；
4. 关系涉及表并入 `filter_table` 候选（空转节点接上真管线）；
5. 生成/纠正 prompt 带关系槽；无声明时明确"不得凭同名列猜 JOIN"；
6. 失效节点清零（验收 21）：filter_table/filter_metric 的输出有真实消费方。
"""

from __future__ import annotations

from typing import Any

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.agent.nodes.generate_sql import build_relations_block, generate_sql
from nl2sql_service.agent.nodes.merge_retrieved_info import merge_retrieved_info
from nl2sql_service.agent.nodes.recall_column import recall_column
from nl2sql_service.agent.nodes.recall_metric import recall_metric
from nl2sql_service.agent.nodes.recall_relation import recall_relation
from nl2sql_service.services.alias_matcher import match_aliases

_ALIASES = [
    {"target_kind": "metric", "target_name": "销售额", "alias": "GMV", "source": "human"},
    {"target_kind": "column", "target_name": "orders.amount", "alias": "成交金额", "source": "human"},
    {"target_kind": "metric", "target_name": "订单数", "alias": "单量", "source": "machine"},  # 未确认
]
_RELATIONS = [
    {
        "left_table": "orders",
        "left_column": "customer_id",
        "right_table": "customers",
        "right_column": "customer_id",
        "relation_type": "many_to_one",
        "note": "同名不同义时以声明为准",
    }
]


class _StubLLM:
    enabled = True

    def __init__(self) -> None:
        self.prompt: str | None = None

    async def invoke(self, prompt: str) -> str:
        self.prompt = prompt
        return "SELECT 1 LIMIT 1"


class _MetaRepo:
    def __init__(self, aliases: list[dict] | None = None, relations: list[dict] | None = None) -> None:
        self._aliases = _ALIASES if aliases is None else aliases
        self._relations = _RELATIONS if relations is None else relations
        self.column_queries: list[list[str]] = []
        self.metric_queries: list[list[str]] = []

    async def list_aliases(self, datasource_id: str = "", tenant_id: str = "", workspace_id: str = "") -> list[dict]:
        return self._aliases

    async def list_relations(self, datasource_id: str = "", tenant_id: str = "", workspace_id: str = "") -> list[dict]:
        return self._relations

    async def find_columns_by_names(
        self, names: list[str], datasource_id: str = "", tenant_id: str = "", workspace_id: str = ""
    ) -> list[dict]:
        self.column_queries.append(names)
        return [{"table_name": "orders", "column_name": "amount", "column_comment": "订单金额", "data_type": "numeric"}]

    async def find_metrics_by_names(
        self, names: list[str], datasource_id: str = "", tenant_id: str = "", workspace_id: str = ""
    ) -> list[dict]:
        self.metric_queries.append(names)
        return [{"metric_name": "销售额", "metric_desc": "订单金额合计", "metric_expr": "SUM(orders.amount)"}]


class _BoomVectorRepo:
    """别名命中时若还走向量路，本 fake 立即炸——证"优先于向量"。"""

    async def recall(self, keywords: list[str], embedding: Any = None, top_k: int = 10) -> list[dict]:
        raise AssertionError("别名精确命中后不应再走向量召回")


def _ctx(meta: Any, vector_repo: Any = None) -> DataAgentContext:
    return DataAgentContext(meta_repository=meta, column_repository=vector_repo, metric_repository=vector_repo)


# ---------------------------------------------------------------------------
# ① 别名精确匹配
# ---------------------------------------------------------------------------
def test_match_aliases_exact_and_substring():
    assert match_aliases("上个月 GMV 是多少", ["上个月"], _ALIASES, "metric") == ["销售额"]
    assert match_aliases("成交金额合计", ["成交", "售额"], _ALIASES, "column") == ["orders.amount"]
    # 机提未确认不参与
    assert match_aliases("单量多少", ["单量"], _ALIASES, "metric") == []
    # 单字别名不搞子串误伤
    assert match_aliases("G", [], [{"target_kind": "metric", "target_name": "x", "alias": "G", "source": "human"}], "metric") == []


async def test_recall_metric_prefers_alias_over_vector():
    meta = _MetaRepo()
    out = await recall_metric(
        {
            "query": "上个月 GMV 是多少",
            "keywords": ["GMV"],
            "context": _ctx(meta, _BoomVectorRepo()),
            "query_embedding": [0.1, 0.2],
            "retrieval_top_k": 10,
        }
    )
    assert out["metrics"] == [{"metric_name": "销售额", "metric_desc": "订单金额合计", "metric_expr": "SUM(orders.amount)"}]
    assert meta.metric_queries == [["销售额"]]


async def test_recall_column_prefers_alias_over_vector():
    meta = _MetaRepo()
    out = await recall_column(
        {
            "query": "统计成交金额",
            "keywords": ["成交金额"],
            "context": _ctx(meta, _BoomVectorRepo()),
            "query_embedding": [0.1, 0.2],
        }
    )
    assert out["columns"][0]["column_name"] == "amount"
    assert meta.column_queries == [["orders.amount"]]


async def test_recall_falls_back_to_vector_when_no_alias_hit():
    class _VectorRepo:
        async def recall(self, keywords: list[str], embedding: Any = None, top_k: int = 10, **_: Any) -> list[dict]:
            return [{"table_name": "orders", "column_name": "order_id"}]

    out = await recall_metric(
        {
            "query": "订单总数",
            "keywords": ["订单", "总数"],
            "context": _ctx(_MetaRepo(aliases=[]), _VectorRepo()),
            "query_embedding": [0.1],
        }
    )
    assert out["metrics"] == [{"table_name": "orders", "column_name": "order_id"}], "无别名命中必须回落向量路"


# ---------------------------------------------------------------------------
# ③ 关系召回（R5）
# ---------------------------------------------------------------------------
async def test_recall_relation_reads_frozen_meta_set():
    out = await recall_relation({"context": _ctx(_MetaRepo()), "datasource_id": "ds-1"})
    assert out["relations"] == _RELATIONS


async def test_recall_relation_prefers_injected_config():
    out = await recall_relation(
        {"metric_config": {"relations": [{"left_table": "a", "left_column": "id", "right_table": "b", "right_column": "a_id"}]}}
    )
    assert out["relations"][0]["left_table"] == "a"


# ---------------------------------------------------------------------------
# ④ 关系涉及表进 filter_table 候选
# ---------------------------------------------------------------------------
async def test_relation_tables_join_filter_table_candidates():
    out = await merge_retrieved_info(
        {
            "columns": [{"table_name": "orders", "column_name": "amount"}],
            "metrics": [],
            "values": [],
            "relations": _RELATIONS,
        }
    )
    assert out["tables"] == [{"table_name": "orders"}, {"table_name": "customers"}], "关系涉及表必须并入候选"


async def test_no_relations_keeps_previous_behaviour():
    out = await merge_retrieved_info(
        {"columns": [{"table_name": "orders", "column_name": "amount"}], "metrics": [], "values": [], "relations": []}
    )
    assert out["tables"] == [{"table_name": "orders"}]


# ---------------------------------------------------------------------------
# ⑤ 生成/纠正 prompt 关系槽
# ---------------------------------------------------------------------------
def test_relations_block_requires_declared_joins():
    block = build_relations_block(_RELATIONS)
    assert "orders.customer_id" in block and "customers.customer_id" in block
    assert "many_to_one" in block
    assert "以声明为准" in block

    assert "不得凭同名列猜测" in build_relations_block([])


async def test_generate_sql_prompt_includes_relations():
    llm = _StubLLM()
    await generate_sql(
        {
            "query": "每个客户的销售额",
            "llm": llm,
            "tables": [],
            "columns": [],
            "metrics": [],
            "values": [],
            "relations": _RELATIONS,
        }
    )
    assert llm.prompt is not None
    assert "orders.customer_id" in llm.prompt, "关系声明必须进生成 prompt"


# ---------------------------------------------------------------------------
# ⑥ 失效节点清零（验收 21）：过滤输出有消费方
# ---------------------------------------------------------------------------
async def test_filter_outputs_have_consumers():
    """filter_table/filter_metric 写回 state 的键必须被生成层读取。

    此前两节点输出零消费方（generate_sql 不读 state.tables/metrics）——
    现在 build_table_infos 读 tables、metric_infos 读 metrics，各一次调用
    即可从 prompt 里观察到（同一 prompt 双断言）。
    """
    llm = _StubLLM()
    await generate_sql(
        {
            "query": "上个月销售额",
            "llm": llm,
            "tables": [{"table_name": "customers", "table_comment": "客户表"}],
            "columns": [],
            "metrics": [{"metric_name": "销售额", "metric_expr": "SUM(orders.amount)"}],
            "values": [],
        }
    )
    assert llm.prompt is not None
    assert "customers" in llm.prompt, "filter_table 的输出必须被生成层消费"
    assert "SUM(orders.amount)" in llm.prompt, "filter_metric 的输出必须被生成层消费"
