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
# 安装（本仓是 uv workspace，在仓库根执行）
uv sync --all-packages

# 初始化元知识库 schema（幂等；首次部署必跑）
python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"
# 查看当前 schema 版本
python -m nl2sql_service.scripts.init_meta_schema --status --dsn "$META_DB_DSN"
# 只列出将执行的迁移，不连库
python -m nl2sql_service.scripts.init_meta_schema --dry-run

# 元知识构建（幂等 upsert：同输入重跑不翻倍；--prune 删源中已不存在的行）
python -m nl2sql_service.scripts.build_meta_knowledge --dsn "$META_DB_DSN" \
  --config nl2sql_service/config/metric_config.example.yaml [--prune]
# --config 只接受 MetricConfig 结构（nl2sql_service/config/metric_config_schema.py）；
# 列/指标/值三类都会写 embedding（维度必须等于 VECTOR_DIM，不等直接报错）；
# 取值的 search_text 必须由构建方写入（value_tsvector 生成列的唯一输入）

# 启动 API server
uvicorn nl2sql_service.api.server:app --host 0.0.0.0 --port 8000
# 或安装后用 console script（读 Settings.host/port）
nl2sql-service

# 就绪探针（k8s readinessProbe）：meta/dw 两池 SELECT 1，任一不可用 503
curl http://localhost:8000/ready
# /health 是共享契约（恒 healthy、不探池），两者用途不同不要合并

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

## 元知识库 schema

DDL 在 `nl2sql_service/migrations/001_meta_schema.up.sql`（回滚见同名 `.down.sql`），是元知识库结构的唯一真相源：

- 表：`nl2sql_column_info` / `nl2sql_metric_info` / `nl2sql_value_info` / `nl2sql_relation_info` / `nl2sql_alias_info` + 版本标记 `nl2sql_schema_meta`（v1）
- v2（`002_meta_lifecycle.up.sql`）：`nl2sql_session_state`（多轮继承四元组 + 已确认 NL→SQL 对）、`nl2sql_query_trace`（P0-4 追溯：召回/绑定/字典命中/成本/双版本号）、`nl2sql_table_stats`（P0-3 行数估值 → 聚合引导）
- `vector(N)` 的维度由 `VECTOR_DIM` 决定，执行时替换；必须与 embedding 模型输出一致
- `nl2sql_value_info.value_tsvector` 是从 `search_text` 生成的列，`search_text` 必须由构建方写入**同一套分词**后的空格拼接结果（写入/查询单源，中英文都走 `simple` 配置）
- 改 schema 一律新增 `00N_*.up.sql`，不回改已入库的旧迁移；所有语句幂等，可重复执行
- 服务启动**不自动建表**（生产库未必给 DDL 权限）；是否自动化待库权限确认后再定

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
