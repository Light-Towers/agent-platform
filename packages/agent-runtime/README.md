# agent-runtime

Plan-F 运行时中间件层。承载横向关注点（重试/超时/熔断/限流/可观测/缓存/回退），Planner 只做决策不持有执行语义。

## 模块职责

### 运行时中间件（顶层）

| 模块 | 职责 |
|------|------|
| `admission.py` / `admission_gateway.py` | 准入限流（令牌桶 + 优先级队列） |
| `coordinator.py` | 会话并发协调（同一 session_id 串行化） |
| `cache.py` | 语义缓存（embedding 相似度命中 + TTL GC） |
| `circuit_breaker.py` | 熔断器（三态机：closed/open/half-open） |
| `revert.py` | 对话回退（LangGraph checkpoint 读取 + 消息截断） |
| `mcp_client.py` | MCP 工具客户端（多 server 连接池 + stack 泄漏防护） |
| `otel.py` / `tracing.py` | OpenTelemetry 追踪（no-op 降级 + Langfuse 集成） |
| `db.py` | 运行时 DB 句柄（连接池管理） |
| `sandbox.py` | 代码执行沙箱（subprocess + Docker 双后端，进程清理） |
| `singleflight.py` | 单飞去重（并发相同请求合并） |
| `schemas.py` | 运行时内部 schema（AdmissionDecision / CoordinationDecision / RevertResult 等） |

### planner/ — Planner 协议与实现

| 模块 | 职责 |
|------|------|
| `protocol.py` | Planner 协议定义（`PlannerRuntime` 抽象） |
| `agentic.py` / `agentic_bridge.py` | AgenticPlanner（LLM 驱动决策 + deepagents 桥接） |
| `registry.py` | Planner 注册表 |
| `policy.py` | Planner 策略（重试/超时/回退策略） |
| `mode_selector.py` | 模式选择（deterministic vs agentic 切换） |
| `context_manager.py` | 上下文管理 |
| `execution_graph.py` / `graph_compose.py` | 执行图组装 |
| `durability.py` / `durability_pg.py` | 持久化（内存 / PostgreSQL checkpoint） |

### skills/ — Skill 注册与执行

| 模块 | 职责 |
|------|------|
| `registry.py` | SkillRegistry（能力注册/发现） |
| `function.py` | Function 执行器（Python 可调用） |
| `agent.py` | Agent 执行器（子代理 invoke） |
| `remote.py` | Remote 执行器（HTTP /invoke 调用） |
| `workflow.py` | Workflow 执行器（DAG 编排） |
| `mcp.py` | MCP 特化注册 |
| `sandbox.py` | Sandbox 特化注册 |
| `middleware.py` | Skill 中间件（前置/后置钩子） |
| `composition.py` / `dag.py` | Skill 组合与 DAG |

### context/ / trajectory/ — 上下文与轨迹

运行时上下文传递与执行轨迹记录。

## 依赖

- `agent-core`（零依赖运行时内核：tracing / guardrails / llm / memory / events / config / resilience）
- `shared-schemas`（联邦契约）

## 演进

源自 `app/infra/*`（2026-08-19 起逐模块迁入）。Phase 0 已完成 9 个运行时模块迁移，`app/infra` 已退役。Phase 1 新增 `skills/` 注册表（Function/Agent/Remote/Workflow 四执行器）。
