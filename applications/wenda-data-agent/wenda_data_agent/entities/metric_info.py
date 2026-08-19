"""MetricInfo：指标信息（pydantic v2）。"""

from pydantic import BaseModel, Field


class MetricInfo(BaseModel):
    metric_name: str = Field(..., description="指标名")
    metric_desc: str = Field("", description="指标描述")
    metric_expr: str = Field("", description="指标表达式")
