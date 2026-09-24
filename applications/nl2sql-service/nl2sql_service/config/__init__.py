"""元知识配置：表/列/指标/值定义的参数化模板与加载器。

metric_config 可经 API 入参注入（/api/query 的 metric_config 字段），
或经预置 Postgres+pgvector 元知识库召回（默认路径）。
"""

from nl2sql_service.config.metric_config_schema import MetricConfig

__all__ = ["MetricConfig"]
