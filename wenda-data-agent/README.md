---
updated: 2026-08-13
---

# wenda-data-agent

Text-to-SQL 数据分析垂直场景 Agent（生产化改造自 `courses/zhanggui-wenda/data-agent/`）。

## 项目定位

LangGraph 异步 12 节点 Text-to-SQL 管线：自然语言 → 关键词抽取 → 表/列/指标/值召回 → 上下文融合 → SQL 生成 → 只读守卫 → 执行 → 纠正循环。

## 来源课程快照

`courses/zhanggui-wenda/data-agent/`（零改动，gitignore 忽略）

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
pip install -e ./wenda-data-agent

# 元知识构建
python -m wenda_data_agent.scripts.build_meta_knowledge --dsn $META_DB_DSN

# 启动 API server
uvicorn wenda_data_agent.api.server:app --host 0.0.0.0 --port 8000

# 查询
curl -X POST http://localhost:8000/api/query -H 'Content-Type: application/json' -d '{"query": "统计上个月销售额"}'
```

## 与既有生产服务关系

- **垂直增强**：与 `app/sql` 通用基础分层。`app/sql` 为基础 Text-to-SQL（4 阶段），`wenda-data-agent` 增强列/指标/值召回 + SQL 纠正循环（12 节点），不强制复用。
- **守卫复用**：`validate_sql` 节点复用 `app/sql/guard.py` 安全语义（单条 SELECT + 禁止 DDL/DML + LIMIT 强制），独立实现。
- **wenda-adapter**：`WENDA_API_URL` 默认指向本服务（可环境变量覆盖回退课程快照）。

## 本地自备资产

- **BGE 权重**：`EMBEDDING_BACKEND=langchain_huggingface` 时需本地自备 BGE 模型权重，非必交付。默认 `langchain_openai` 无需本地权重。
- **Postgres + pgvector**：需自备 Postgres 实例 + pgvector 扩展。

## 配置

环境变量（`.env`）或 `conf/app_config.yaml` + `conf/meta_config.yaml`：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `META_DB_DSN` | 元知识库 Postgres DSN | （空，必填） |
| `DW_DB_DSN` | 业务数仓 Postgres DSN（只读） | （空，必填） |
| `LLM_API_KEY` | LLM API 密钥 | （空） |
| `EMBEDDING_BACKEND` | `langchain_openai` \| `langchain_huggingface` | `langchain_openai` |
| `SQL_READ_ONLY_GUARD` | SQL 只读守卫（强制 true） | `true` |
| `TOKENIZER` | `jieba` \| `bigram` | `bigram` |
