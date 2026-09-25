---
updated: 2026-09-22
---

# nl2sql-service

通用 Text-to-SQL 数据分析服务。LangGraph 异步 12 节点管线，元知识（表/列/指标/值定义）参数化，可经配置文件或 API 入参注入，不硬编码特定业务表结构。

## 项目定位

LangGraph 异步 12 节点 Text-to-SQL 管线：自然语言 → 关键词抽取 → 表/列/指标/值召回 → 上下文融合 → SQL 生成 → 只读守卫 → 执行 → 纠正循环。

## 技术栈

- **FastAPI** + **uvicorn**：异步 API server
- **LangGraph**：异步 StateGraph 12 节点编排
- **langchain-openai**：LLM + Embedding（可插拔）
- **psycopg** + **pgvector**：Postgres 客户端 + 向量召回
- **sqlglot**：SQL 白名单只读守卫
- **pydantic v2** + **pydantic-settings**：数据模型 + 配置
- **agent-core.logging**：统一日志

## 运行方式

```bash
# 安装
pip install -e ./nl2sql-service

# 元知识构建
python -m nl2sql_service.scripts.build_meta_knowledge --dsn $META_DB_DSN

# 启动 API server
uvicorn nl2sql_service.api.server:app --host 0.0.0.0 --port 8000

# 查询（元知识走预置配置库）
curl -X POST http://localhost:8000/api/query -H 'Content-Type: application/json' -d '{"query": "统计上个月销售额"}'

# 查询（入参注入元知识，不经预置库）
curl -X POST http://localhost:8000/api/query -H 'Content-Type: application/json' -d '{
  "query": "统计上个月销售额",
  "metric_config": {
    "tables": [{"table_name": "orders", "table_comment": "订单表"}],
    "columns": [{"table_name": "orders", "column_name": "amount", "column_comment": "金额", "data_type": "numeric"}],
    "metrics": [{"metric_name": "销售额", "metric_desc": "订单金额合计", "metric_expr": "SUM(amount)"}],
    "values": []
  }
}'
```

## 元知识参数化

元知识（表/列/指标/值定义）有两种注入方式：

1. **预置配置库**：写入 Postgres + pgvector 元知识库，经召回节点向量/全文检索（默认路径，需 `META_DB_DSN`）。
2. **API 入参注入**：`/api/query` 入参 `metric_config` 直接携带表/列/指标/值定义，召回节点优先使用入参，不查元知识库。适合无元知识库的轻量场景或临时查询。

元知识配置模板见 `nl2sql_service/config/metric_config.example.yaml`。

## 与既有生产服务关系

- **垂直增强**：与 `applications/agent_server/sql/` 通用基础分层。`applications/agent_server/sql/` 为基础 Text-to-SQL（4 阶段），`nl2sql-service` 增强列/指标/值召回 + SQL 纠正循环（12 节点），不强制复用。
- **守卫复用**：`validate_sql` 节点复用 `agent_core.sql.guard` 安全语义（单条 SELECT + 禁止 DDL/DML + LIMIT 强制）。

## 本地自备资产

- **BGE 权重**：`EMBEDDING_BACKEND=langchain_huggingface` 时需本地自备 BGE 模型权重，非必交付。默认 `langchain_openai` 无需本地权重。
- **Postgres + pgvector**：需自备 Postgres 实例 + pgvector 扩展（仅预置配置库路径需要）。

## 配置

环境变量（`.env`）或 `conf/app_config.yaml` + `conf/meta_config.yaml`：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `META_DB_DSN` | 元知识库 Postgres DSN | （空，预置库路径必填） |
| `DW_DB_DSN` | 业务数仓 Postgres DSN（只读） | （空，必填） |
| `LLM_API_KEY` | LLM API 密钥 | （空） |
| `EMBEDDING_BACKEND` | `langchain_openai` \| `langchain_huggingface` | `langchain_openai` |
| `SQL_READ_ONLY_GUARD` | SQL 只读守卫（强制 true） | `true` |
| `TOKENIZER` | `jieba` \| `bigram` | `bigram` |
| `TABLE_PREFIX` | 元知识库表名前缀 | `nl2sql_` |
