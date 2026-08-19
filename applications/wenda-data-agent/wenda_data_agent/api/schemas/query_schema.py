"""查询 Schema：复用 shared-schemas 的 QueryResponse/QueryData 契约。"""

from pydantic import Field
from shared_schemas import QueryRequest, QueryResponse


class SqlQueryRequest(QueryRequest):
    """Text-to-SQL 查询请求。"""



class SqlQueryResponse(QueryResponse):
    """Text-to-SQL 查询响应。"""

    sql: str | None = Field(None, description="生成的 SQL")
    error: str | None = Field(None, description="错误信息")
