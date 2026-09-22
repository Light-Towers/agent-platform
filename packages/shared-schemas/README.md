# shared-schemas

联邦 4 服务共享的 Pydantic v2 契约包。零框架依赖（仅 pydantic），确保跨服务类型安全。

## 公开 API

| 契约 | 模块 | 用途 |
|------|------|------|
| `QueryRequest` / `QueryResponse` / `QueryData` | `query.py` | 统一查询请求/响应（所有子服务 `/invoke` 端点共用） |
| `ThreadState` / `empty_thread_state` / `message_dict` | `thread.py` | 统一线程状态（双 Planner checkpoint 共享） |
| `HealthResponse` / `DependencyHealth` / `HealthStatus` | `health.py` | 统一健康检查响应（含能力标志位） |
| `IntentResult` / `IntentCandidate` | `intent.py` | 意图分类结果 |
| `SubagentCall` / `SubagentResult` | `subagent.py` | 子代理调用/返回契约 |
| `sse_pack` | `sse.py` | SSE 帧打包（event 空时退化为纯 data 行，向后兼容） |

## 设计要点

- `QueryRequest.session_id` 用 `AliasChoices("session_id", "thread_id")` 兼容旧字段名（2026-08-21 前契约）。
- `ThreadState` 两段式：`messages`（LangChain BaseMessage 序列化形态）+ `metadata`（编排状态），双 Planner 各自读写子集互不干扰。契约版本 `THREAD_STATE_VERSION = 1`。
- `HealthResponse` 含 8 个能力标志位（storage/llm/search/sql_backend/coordination/admission/revert/otel/mcp），各服务按需贡献，默认 False/None 向后兼容。

## 使用

```python
from shared_schemas import QueryRequest, QueryResponse, ThreadState, sse_pack
```

## 消费方

- `applications/agent_federation/` — 联邦网关
- `applications/kefu-service/` — 客服服务（`/invoke` 返回 `QueryResponse`）
- `applications/wenda-data-agent/` — Text-to-SQL 数据分析
- `applications/agent_server/` — 统一 Agent 平台（SSE 响应用 `sse_pack`）
