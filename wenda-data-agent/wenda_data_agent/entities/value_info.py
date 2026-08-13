"""ValueInfo：值信息（pydantic v2）。"""

from pydantic import BaseModel, Field


class ValueInfo(BaseModel):
    column_name: str = Field(..., description="列名")
    value: str = Field(..., description="值")
    value_desc: str = Field("", description="值描述")
