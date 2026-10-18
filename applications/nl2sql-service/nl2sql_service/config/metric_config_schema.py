"""MetricConfig：元知识配置 schema（表/列/指标/值定义）——**运行契约单源**。

经 API 入参注入或 YAML 配置加载（`scripts/build_meta_knowledge` 的
`--config` 也只认本模型），驱动召回节点与构建入口，不硬编码特定业务表结构。

2026-10-18（方案 P2 / D1）：此前的 `entities/` 五件套（TableInfo/
ColumnInfo/ColumnMetric/MetricInfo/ValueInfo）只被契约测试引用、零运行
引用，与本模型形成双契约——测试给不参与的契约兜底，改运行契约不会红。
entities/ 已删，契约测试（tests/test_nl2sql_contracts.py）整体指向本模块。
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
