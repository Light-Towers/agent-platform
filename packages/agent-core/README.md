# agent-core

框架无关的 Agent 运行时内核，可被任意宿主应用（如掌柜智库 zhanggui-zhiku）以
`import agent_core` 方式复用。

## 组件

| 模块 | 公开 API | 依赖 |
|---|---|---|
| `agent_core.tracing` | init_tracing / get_tracer / start_span / traced_span / generate_request_id / set_request_context / get_request_id / user_query_hash / is_tracing_enabled | 仅 stdlib（OTel 为 extra） |
| `agent_core.metrics.retrieval` | recall_at_k / hit_rate_at_k / mrr / dcg_at_k / ndcg_at_k / compute_retrieval_metrics | 纯 stdlib |
| `agent_core.guardrails.auth` | extract_api_key_from_headers / resolve_client_key / is_health_path / should_skip_* / format_validation_error | 纯 stdlib |
| `agent_core.guardrails.ratelimit` | SlidingWindowRateLimiter / apply_api_rate_limit | 纯 stdlib |
| `agent_core.guardrails.web` | SecurityGuardsMiddleware | extra `web`（starlette） |
| `agent_core.llm` | register_provider / get_llm_client / BaseLLMProvider | 协议层纯 stdlib（openai 适配器 extra `llm-openai`） |
| `agent_core.memory` | ConversationMemory / MongoHistoryStore | base 纯 stdlib；mongo 实现 extra `memory-mongo` |
| `agent_core.tools` | Tool / ToolRegistry / guarded_invoke / wrap_tool / MCPToolAdapter | base/registry/guarded 纯 stdlib；mcp 适配器 extra `tools-mcp` |
| `agent_core.resilience` | retry / timeout / CircuitBreaker（STATE_* 常量） / validate_config | 纯 stdlib |
| `agent_core.events` | EventSink / EventBus / CallbackSink / LegacyStreamSink / OTelSpanSink（WS-4 统一事件出口） | 纯 stdlib |
| `agent_core.config` | env_bool / env_int / env_float / env_str / env_database_url / KernelConfig（WS-5） | 纯 stdlib |
| `agent_core.memory.store` | MemoryStore / PgMemoryStore / VectorMemoryStore / CapabilityReport（WS-1） | 纯 stdlib |

## 环境变量清单（新增 env 必须登记）

| 变量 | 默认值 | 所属模块 | 用途 |
|---|---|---|---|
| `SEMANTIC_MEMORY_ENABLED` | `false` | memory.semantic | 语义记忆总开关（唯一总开关） |
| `SEMANTIC_MEMORY_TYPED` | `true` | memory.typed | typed 加权策略开关（WS-1 起默认开；不再决定走哪条栈） |
| `SEMANTIC_MEMORY_COLLECTION` | `semantic_memory` | memory.semantic | 向量集合/表名 |
| `VECTOR_BACKEND` | `milvus` | memory.semantic | 向量后端（`milvus` \| `pg`） |
| `MILVUS_URI` / `MILVUS_TOKEN` | `http://localhost:19530` / `""` | memory.semantic | Milvus 连接 |
| `AGENT_PLATFORM_DATABASE_URL` | 回退 `DATABASE_URL` | config | pg 后端 URL；旧名 `DEEPAGENTS_DATABASE_URL` 兼容一个小版本 |
| `TENANT_ID` | `default` | memory | 多租户隔离 |
| `MEMORY_FORGET_THRESHOLD` | `0.1` | memory.typed | consolidate 重要度阈值 |
| `MEMORY_FORGET_AGE_DAYS` | `30` | memory.typed | consolidate 老化天数 |
| `EMBEDDING_MODE` / `EMBEDDING_DIM` | `auto` / `512` | memory.embedder | embedder 选型（mock 维度） |
| `SILICONFLOW_API_KEY` | `""` | memory.embedder | 配了则 embedding 走远程硅基流动 |
| `MONGO_URL` / `MONGO_DB` | `""` / `deepagents` | memory | Mongo 会话历史/checkpoint |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `AGENT_CORE_TRACE_ENABLED` | `""` / `false` | tracing | OTel 导出总开关 |

## 安装

```bash
uv sync --extra tracing --extra web --extra memory-mongo --extra tools-mcp
# 或
pip install -e ".[tracing,web,memory-mongo,tools-mcp]"
```

## 设计铁律

- 内核绝不 import `app.core.config` / `langgraph` 等宿主应用依赖；
- 所有重型/可选第三方依赖（OTel / langchain / pymongo / starlette / openai-agents）
  全部懒导入 + 标 extra，使纯模块仅 stdlib 即可 import；
- 日志自包含：`from agent_core.logging import get_logger`。
