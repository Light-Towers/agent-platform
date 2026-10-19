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
    table_name: str = Field("", description="所属表名（#117：同名列跨表共存与回溯；缺省空兼容存量配置）")


class MetricRelation(BaseModel):
    """表间关系声明（§5.14-R1，MDL relationships 的最小子集，不造 DSL）。

    `relation_type` 是未来类型化属性（本体方向 R7）的种子槽位——挂起期间
    不建类型系统，但不得写死成无类型扁平串（foreclose 升级路径）。
    """

    left_table: str = Field(..., description="左表")
    left_column: str = Field(..., description="左表列")
    right_table: str = Field(..., description="右表")
    right_column: str = Field(..., description="右表列")
    relation_type: str = Field("many_to_one", description="many_to_one | one_to_one | one_to_many")
    note: str = Field("", description="备注（同名不同义的消歧说明）")


class MetricAlias(BaseModel):
    """别名/同义词声明（§5.14-R1）：GMV→销售额 这类口语变体的登记载体。

    同时是 P0-5"别名精确匹配优先于向量"主路的已登记短语来源——P0-5 管
    怎么检索，本契约管声明从哪来（产销关系）。
    """

    target_kind: str = Field(..., description="table | column | metric")
    target_name: str = Field(..., description="目标名（表/列/指标名）")
    alias: str = Field(..., description="别名")
    source: str = Field("human", description="human | machine（机提未确认前不参与召回）")


class MetricConfig(BaseModel):
    """元知识配置：表/列/指标/值/关系/别名定义集合。"""

    tables: list[MetricTable] = Field(default_factory=list, description="表定义")
    columns: list[MetricColumn] = Field(default_factory=list, description="列定义")
    metrics: list[MetricDef] = Field(default_factory=list, description="指标定义")
    values: list[MetricValue] = Field(default_factory=list, description="值定义")
    relations: list[MetricRelation] = Field(default_factory=list, description="表间关系声明（§5.14-R1）")
    aliases: list[MetricAlias] = Field(default_factory=list, description="别名/同义词声明（§5.14-R1）")

    def to_recall_result(self) -> dict[str, list[dict]]:
        """转为召回节点返回格式（list[dict]），供召回节点直接使用。"""
        return {
            "tables": [t.model_dump() for t in self.tables],
            "columns": [c.model_dump() for c in self.columns],
            "metrics": [m.model_dump() for m in self.metrics],
            "values": [v.model_dump() for v in self.values],
            "relations": [r.model_dump() for r in self.relations],
            "aliases": [a.model_dump() for a in self.aliases],
        }
