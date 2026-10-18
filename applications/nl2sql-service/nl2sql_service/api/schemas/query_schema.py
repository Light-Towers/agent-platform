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
    # P1-3/P1-6：用户显式选源；不传 = 服务端默认源。未知 id 由服务端 fail-fast
    # （不静默回落——串源比报错更糟）。dialect 由所选源决定，无需客户端指定。
    datasource_id: str | None = Field(None, description="数据源 ID（显式选源；缺省用服务端默认源）")


class SqlQueryResponse(QueryResponse):
    """Text-to-SQL 查询响应。"""

    sql: str | None = Field(None, description="生成的 SQL")
    error: str | None = Field(None, description="错误信息（对外分类消息；DB 原文只在 error_detail 内，不随响应返回）")
    # P1-3② 口径标签：答案里能看出这个数字来自哪个源、什么口径
    # （如"数仓 T+1、已清洗" / "业务库、实时未清洗"）。
    datasource_label: str | None = Field(None, description="命中数据源的口径标签")
    # P0-8④：取值匹配语义上响应体——调用方能区分"字面量命中字典/源"与
    # "未命中"，未命中时按未识别取值处理，不要把 0 行当成答案。
    matched_values: list[str] = Field(default_factory=list, description="已在字典/源侧确认存在的取值")
    unmatched_terms: list[str] = Field(default_factory=list, description="确定性未匹配的取值（探不到的不在内）")
    dict_hit: bool = Field(False, description="全部字面量都有确定结论（无 unknown）")
    empty_result_reason: str | None = Field(None, description="零结果分诊结论：unrecognized_literal / genuinely_empty / no_dimension_filter")
    path: str | None = Field(None, description="graph | metric_direct | refuse（P2 双路径一致性对比维度）")
