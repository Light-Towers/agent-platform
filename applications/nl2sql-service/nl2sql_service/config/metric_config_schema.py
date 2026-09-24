"""MetricConfig：元知识配置 schema（表/列/指标/值定义）。

经 API 入参注入或 YAML 配置加载，驱动召回节点，不硬编码特定业务表结构。
与 entities/ 下 TableInfo/ColumnInfo/MetricInfo/ValueInfo 契约一致（dict 视图）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MetricTable(BaseModel):
    table_name: str = Field(..., description="表名")
    table_comment: str = Field("", description="表注释")


class MetricColumn(BaseModel):
    table_name: str = Field(..., description="所属表名")
    column_name: str = Field(..., description="列名")
    column_comment: str = Field("", description="列注释")
    data_type: str = Field("", description="数据类型")


class MetricDef(BaseModel):
    metric_name: str = Field(..., description="指标名")
    metric_desc: str = Field("", description="指标描述")
    metric_expr: str = Field("", description="指标表达式")


class MetricValue(BaseModel):
    column_name: str = Field(..., description="所属列名")
    value: str = Field(..., description="值")
    value_desc: str = Field("", description="值描述")


class MetricConfig(BaseModel):
    """元知识配置：表/列/指标/值定义集合。"""

    tables: list[MetricTable] = Field(default_factory=list, description="表定义")
    columns: list[MetricColumn] = Field(default_factory=list, description="列定义")
    metrics: list[MetricDef] = Field(default_factory=list, description="指标定义")
    values: list[MetricValue] = Field(default_factory=list, description="值定义")

    def to_recall_result(self) -> dict[str, list[dict]]:
        """转为召回节点返回格式（list[dict]），供召回节点直接使用。"""
        return {
            "tables": [t.model_dump() for t in self.tables],
            "columns": [c.model_dump() for c in self.columns],
            "metrics": [m.model_dump() for m in self.metrics],
            "values": [v.model_dump() for v in self.values],
        }
