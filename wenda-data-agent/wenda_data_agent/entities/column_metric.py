"""ColumnMetric：列指标关联（pydantic v2）。"""

from pydantic import BaseModel, Field


class ColumnMetric(BaseModel):
    column_name: str = Field(..., description="列名")
    metric_name: str = Field(..., description="指标名")
    metric_expr: str = Field("", description="指标表达式")
