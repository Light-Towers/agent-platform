"""ColumnInfo：列信息（pydantic v2）。"""

from pydantic import BaseModel, Field

from wenda_data_agent.entities.column_metric import ColumnMetric


class ColumnInfo(BaseModel):
    column_name: str = Field(..., description="列名")
    column_comment: str = Field("", description="列注释")
    data_type: str = Field("", description="数据类型")
    metrics: list[ColumnMetric] = Field(default_factory=list, description="列关联指标")
