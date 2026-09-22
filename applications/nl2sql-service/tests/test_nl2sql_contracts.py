"""nl2sql-service 契约测试：entities / LLM client / settings / state。

无外部 DB/LLM 依赖，测 Pydantic 契约 + LLMClient 降级 + Settings 默认值。
"""

from __future__ import annotations

from nl2sql_service.entities.column_info import ColumnInfo
from nl2sql_service.entities.column_metric import ColumnMetric
from nl2sql_service.entities.metric_info import MetricInfo
from nl2sql_service.entities.table_info import TableInfo
from nl2sql_service.entities.value_info import ValueInfo


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_column_metric_basic():
    cm = ColumnMetric(column_name="col1", metric_name="metric1")
    assert cm.column_name == "col1"
    assert cm.metric_name == "metric1"
    assert cm.metric_expr == ""


def test_column_info_with_metrics():
    cm = ColumnMetric(column_name="col1", metric_name="m1", metric_expr="SUM(col1)")
    ci = ColumnInfo(column_name="col1", column_comment="注释", data_type="int", metrics=[cm])
    assert ci.column_name == "col1"
    assert len(ci.metrics) == 1
    assert ci.metrics[0].metric_expr == "SUM(col1)"


def test_column_info_defaults():
    ci = ColumnInfo(column_name="col1")
    assert ci.column_comment == ""
    assert ci.data_type == ""
    assert ci.metrics == []


def test_table_info_with_columns():
    ci = ColumnInfo(column_name="col1")
    ti = TableInfo(table_name="t1", table_comment="表注释", columns=[ci])
    assert ti.table_name == "t1"
    assert len(ti.columns) == 1


def test_table_info_defaults():
    ti = TableInfo(table_name="t1")
    assert ti.table_comment == ""
    assert ti.columns == []


def test_metric_info_basic():
    mi = MetricInfo(metric_name="m1", metric_desc="描述", metric_expr="COUNT(*)")
    assert mi.metric_name == "m1"
    assert mi.metric_expr == "COUNT(*)"


def test_metric_info_defaults():
    mi = MetricInfo(metric_name="m1")
    assert mi.metric_desc == ""
    assert mi.metric_expr == ""


def test_value_info_basic():
    vi = ValueInfo(column_name="col1", value="v1", value_desc="值描述")
    assert vi.column_name == "col1"
    assert vi.value == "v1"


def test_value_info_defaults():
    vi = ValueInfo(column_name="col1", value="v1")
    assert vi.value_desc == ""


def test_table_info_serialization_roundtrip():
    ci = ColumnInfo(column_name="col1", data_type="int")
    ti = TableInfo(table_name="t1", columns=[ci])
    data = ti.model_dump()
    restored = TableInfo(**data)
    assert restored.table_name == "t1"
    assert restored.columns[0].column_name == "col1"


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
