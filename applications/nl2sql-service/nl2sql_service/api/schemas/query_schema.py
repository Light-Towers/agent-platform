"""查询 Schema：复用 shared-schemas 的 QueryResponse/QueryData 契约。"""

from pydantic import Field
from shared_schemas import QueryRequest, QueryResponse

from nl2sql_service.config.metric_config_schema import MetricConfig


class SqlQueryRequest(QueryRequest):
    """Text-to-SQL 查询请求。

    metric_config 可选注入元知识（表/列/指标/值定义）；
    传入时召回节点优先使用入参，不查预置元知识库。
    """

    metric_config: MetricConfig | None = Field(None, description="元知识配置（表/列/指标/值定义）")


class SqlQueryResponse(QueryResponse):
    """Text-to-SQL 查询响应。"""

    sql: str | None = Field(None, description="生成的 SQL")
    error: str | None = Field(None, description="错误信息")
