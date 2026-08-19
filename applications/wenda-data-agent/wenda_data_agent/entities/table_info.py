"""TableInfo：表信息（pydantic v2）。"""

from pydantic import BaseModel, Field

from wenda_data_agent.entities.column_info import ColumnInfo


class TableInfo(BaseModel):
    table_name: str = Field(..., description="表名")
    table_comment: str = Field("", description="表注释")
    columns: list[ColumnInfo] = Field(default_factory=list, description="列信息")
