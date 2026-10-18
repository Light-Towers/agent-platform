"""训练数据摄入 Schema（A 方案 Stage ③：替代 agent_server `/sql/train`）。"""

from pydantic import BaseModel, Field


class IngestExample(BaseModel):
    """一条 NL→SQL 范例（与 sql_examples 行同构）。"""

    question: str = Field(..., description="自然语言问题（自然键：同问法 upsert 更新 SQL）")
    sql: str = Field("", description="对应的只读 SELECT SQL")
    source: str = Field("human", description="human=人工整理；machine=机提（未确认不进召回）")


class IngestRequest(BaseModel):
    """摄入请求：DDL / 业务文档 / 范例（均可空，但全空 = 无事可做，400）。

    形状对齐 agent_server `SqlTrainRequest`（ddl/documentation/question+sql），
    使 `/sql/train` 的调用方可以近乎一对一改投本端点。
    """

    ddl: str | list[str] = Field(default_factory=list, description="CREATE TABLE DDL 文本（可多条）")
    docs: str | list[str] = Field(default_factory=list, description="业务文档自由文本（可多条）")
    examples: list[IngestExample] = Field(default_factory=list, description="NL→SQL 范例")
    # 作用域（P1-1 隔离）：tenant 按 ADR-0007 服务端断言 > 本字段 > default_tenant；
    # workspace 取本字段 > default_workspace。datasource 缺省取服务端默认源。
    tenant_id: str | None = Field(None, description="租户（服务端断言优先；缺省单租户 dev）")
    workspace_id: str | None = Field(None, description="工作区（归属细维）")
    datasource_id: str | None = Field(None, description="数据源 ID（缺省服务端默认源）")


class IngestReport(BaseModel):
    """摄入结果：写入计数 + 三类记账（坏 DDL / 未命中文档 / 空 question）。

    记账列表**必须**回传——静默丢 = 调用方以为喂进去了，其实没有（迁移与在线
    摄入同一条纪律：宁缺勿错，缺的那部分要看得见）。
    """

    columns: dict[str, int] = Field(default_factory=dict, description="列行 {inserted, updated}")
    examples: dict[str, int] = Field(default_factory=dict, description="范例行 {inserted, updated}")
    tenant_id: str = Field("", description="实际落点作用域（租户）")
    workspace_id: str = Field("", description="实际落点作用域（工作区）")
    datasource_id: str = Field("", description="实际落点作用域（数据源）")
    skipped_ddl: list[str] = Field(default_factory=list, description="解析失败/不支持的 DDL（截断）")
    unmapped_docs: list[str] = Field(default_factory=list, description="未命中任何表名的文档（截断）")
    skipped_examples: list[str] = Field(default_factory=list, description="空 question 等被跳过的范例")
