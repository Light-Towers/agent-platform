"""nl2sql-service 契约测试：MetricConfig / LLM client / settings / state。

无外部 DB/LLM 依赖，测 Pydantic 契约 + LLMClient 降级 + Settings 默认值。

2026-10-18（方案 P2 / D1 双契约清理）：此前本节测 `entities/` 五件套，而
运行契约是 `config/metric_config_schema.py` 的 MetricConfig——测试给不参与
运行的契约兜底，真契约无测试（"改运行契约不会红"）。entities/ 已删，
本节整体重定向到 MetricConfig。
"""

from __future__ import annotations

import pytest
from nl2sql_service.config.metric_config_schema import (
    MetricColumn,
    MetricConfig,
    MetricDef,
    MetricTable,
    MetricValue,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# MetricConfig（运行契约单源）
# ---------------------------------------------------------------------------
def test_metric_table_defaults():
    t = MetricTable(table_name="orders")
    assert t.table_name == "orders"
    assert t.table_comment == ""


def test_metric_table_requires_table_name():
    with pytest.raises(ValidationError):
        MetricTable()


def test_metric_column_basic():
    c = MetricColumn(table_name="orders", column_name="amount", column_comment="订单金额", data_type="numeric")
    assert c.model_dump() == {
        "table_name": "orders",
        "column_name": "amount",
        "column_comment": "订单金额",
        "data_type": "numeric",
    }


def test_metric_column_requires_table_and_column():
    with pytest.raises(ValidationError):
        MetricColumn(column_name="amount")  # table_name 必填
    with pytest.raises(ValidationError):
        MetricColumn(table_name="orders")  # column_name 必填


def test_metric_def_basic_and_defaults():
    m = MetricDef(metric_name="销售额", metric_desc="订单金额合计", metric_expr="SUM(orders.amount)")
    assert m.metric_name == "销售额"
    assert m.metric_expr == "SUM(orders.amount)"

    bare = MetricDef(metric_name="订单数")
    assert bare.metric_desc == ""
    assert bare.metric_expr == ""


def test_metric_value_requires_column_and_value():
    v = MetricValue(column_name="customers.customer_name", value="VIP", value_desc="VIP 客户")
    assert v.model_dump() == {
        "column_name": "customers.customer_name",
        "value": "VIP",
        "value_desc": "VIP 客户",
    }
    with pytest.raises(ValidationError):
        MetricValue(column_name="city")  # value 必填


def test_metric_config_to_recall_result_shape():
    """召回节点消费的形状：四段齐全、字段名即运行契约（改名即红）。"""
    config = MetricConfig(
        tables=[{"table_name": "orders", "table_comment": "订单表"}],
        columns=[{"table_name": "orders", "column_name": "amount", "column_comment": "金额", "data_type": "numeric"}],
        metrics=[{"metric_name": "销售额", "metric_desc": "订单金额合计", "metric_expr": "SUM(orders.amount)"}],
        values=[{"column_name": "order_status", "value": "已支付", "value_desc": ""}],
    )
    result = config.to_recall_result()

    assert set(result) == {"tables", "columns", "metrics", "values"}
    assert result["tables"][0] == {"table_name": "orders", "table_comment": "订单表"}
    assert result["metrics"][0]["metric_expr"] == "SUM(orders.amount)"
    assert result["values"][0]["value"] == "已支付"


def test_metric_config_defaults_to_empty_sections():
    config = MetricConfig()
    assert config.to_recall_result() == {"tables": [], "columns": [], "metrics": [], "values": []}


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------
def test_llm_client_not_enabled():
    from nl2sql_service.agent.llm import LLMClient

    client = LLMClient(api_key="")
    assert not client.enabled


def test_llm_client_enabled():
    from nl2sql_service.agent.llm import LLMClient

    client = LLMClient(api_key="test-key", model="gpt-4o-mini")
    assert client.enabled


async def test_llm_client_invoke_no_api_key():
    from nl2sql_service.agent.llm import LLMClient

    client = LLMClient(api_key="")
    result = await client.invoke("test prompt")
    assert result == ""


async def test_llm_client_invoke_exception_returns_empty():
    """LLM 调用异常时返回空字符串（不抛异常）。"""
    from nl2sql_service.agent.llm import LLMClient

    client = LLMClient(api_key="test-key", model="gpt-4o-mini")
    result = await client.invoke("test prompt")
    assert result == ""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def test_settings_defaults():
    from nl2sql_service.conf.settings import Settings

    s = Settings()
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.table_prefix == "nl2sql_"
    assert s.retrieval_top_k == 10
    assert s.rrf_k == 60
    assert s.sql_read_only_guard is True
    assert s.tokenizer == "bigram"


def test_settings_db_enabled_flags():
    from nl2sql_service.conf.settings import Settings

    s = Settings()
    assert not s.meta_db_enabled
    assert not s.dw_db_enabled

    s2 = Settings(meta_db_dsn="postgresql://localhost/db", dw_db_dsn="postgresql://localhost/dw")
    assert s2.meta_db_enabled
    assert s2.dw_db_enabled


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------
def test_data_agent_state_keys():
    from nl2sql_service.agent.state import DataAgentState

    state: DataAgentState = {"query": "test", "keywords": ["a", "b"]}
    assert state["query"] == "test"
    assert state["keywords"] == ["a", "b"]


# ---------------------------------------------------------------------------
# BaseRepository protocol
# ---------------------------------------------------------------------------
def test_base_repository_protocol():

    class FakeRepo:
        async def recall(self, keywords, embedding=None, top_k=10):
            return [{"keyword": k} for k in keywords]

    repo = FakeRepo()
    assert hasattr(repo, "recall")
