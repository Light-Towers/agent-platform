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
| `agent_core.resilience` | retry / timeout / CircuitBreaker / validate_config | 纯 stdlib |

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
