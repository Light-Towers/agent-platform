# 技术债务追踪：多 Agent 实现遗留问题

> **创建时间**：2026-09-23
> **来源**：多 Agent 架构三层扫描（编排/通信/运行时）+ 逐条实跑核验
> **已修**：P0×4 + P1×3 + C×14（18+3 条）+ B-2/B-3/B-4/B-5a，**豁免**：B-1/B-5b

## 已修复（第一批 P0+P1）

| # | 缺陷 | 文件 | 修复方式 |
|---|------|------|---------|
| P0-1 | federation `init_pool`/`close_pool` ImportError | `agent_federation/agent/db.py` | 补 re-export + `__all__` |
| P0-2 | admission 装配键名不匹配 | `agent_server/api/routes.py` | `admission_queue` → `admission_controller` |
| P0-3 | OTel `set_attribute` 对 CM 崩溃 | `agent_server/api/routes.py` | `_span_cm.__enter__()` 取真实 span |
| P0-4 | `mark_completed` 三参数 execute | `agent_runtime/admission.py` | 去掉多余第三参数 |
| P1-1 | federation Runtime 缺 `max_duration_seconds` | `agent_federation/planners/__init__.py` | 加 `FED_MAX_DURATION_SECONDS` 默认 60 |
| P1-2 | rag_query 端点配错 | `agent_federation/agent/config.py` | `/api/messages` → `/query` |
| P1-3 | 语义缓存跨租户 + knowledge /history 无租户 | `cache.py` / `db.py` / `routes.py` / `mongo.py` / `query_router.py` | 加 `tenant_id` 参数 + WHERE 过滤 + DDL 加列 |

## 已修复（第二批 C 组）

| # | 缺陷 | 文件 | 修复方式 |
|---|------|------|---------|
| C-9 | health_check 404 误判 | `health_check.py` | `/health` 非 200 时 fall through 到 fallback |
| C-5 | 无 recursion_limit | `main_agent.py` | config 加 `recursion_limit` 默认 50 |
| C-10 | 默认端口冲突 | `knowledge_service/core/config.py` | 默认端口 8000 → 8900 |
| C-6 | select_skill 未知 skill 静默落默认 | `exhibition_agent/graph/nodes.py` | 加 `skill_error` + run_skill 检查 |
| C-12 | sandbox env 泄漏 | `agent_runtime/sandbox.py` | 白名单 env（PATH/SystemRoot/TEMP 等） |
| C-4 | deterministic 异常炸断 SSE | `agent_server/api/routes.py` | `_stream()` 加 except yield error+done |
| C-13 | 健康探活标记对已构造 subagent 失效 | `async_subagents.py` | `_svc` → `_svc_key` 动态查 + healthy fallback |
| C-14 | /api/task 无超时+异常静默 | `agent_federation/api/server.py` | 加 wait_for + try/except |
| C-11 | singleflight 互斥失效 | `agent_runtime/singleflight.py` | lock 延迟 300s 移除（与结果缓存同步） |
| C-7 | SQL 元知识跨租户 | `db.py` / `schema_store.py` | 加 workspace_id 列 + WHERE 过滤 |
| C-8 | knowledge /api/v1/retrieve 无租户 | `query_router.py` | RetrieveRequest 加 tenant_id/scope_type + 透传 |

## 未修：B 组（架构落差）

### B-1: 4/7 应用零接入 Runtime（豁免）
kefu / nl2sql / knowledge / dialogue-framework 完全无 admission / coordinator / durability / 统一 Skill 治理。
**决策**：这些服务各有自己的框架（LangGraph/deepagents），强行接入 agent-runtime 违反"框架选型偏好"。明确声明豁免——轻量服务不需要 Runtime 中间件，中间件由消费方（agent_server/federation）承担。

### B-2: federation PlannerRuntime 缺 pool/checkpoint/trajectory/llm 注入（已修）
`planners/__init__.py` 已加 `_build_pg_stores()` + `_build_llm()` 懒构建注入 `get_planner_runtime()`，pool 不可用时退化为 None。

### B-3: agentic 默认绕过 skill_guard（已修）
`main_agent.py` astream 循环中加 task tool 调用计数，超 max_steps 中止。

### B-4: WS 路径绕过全部中间件（已修）
`api/server.py` 的 `/ws/{thread_id}` 已加 `start_span("ws.query")` + 异常日志。admission/coordinator 暂未接入（WS 长连接语义与 HTTP 请求不同，需专门设计）。

### B-5: 一批中间件零装配（B-5a 已修，B-5b 豁免）
B-5a: SkillRegistry 已装配 RetryMiddleware + AuditMiddleware（agent_server + agent_federation）。
B-5b: ExecutionScheduler/ControlPlane/WorkingMemory/ExecutionRecovery 豁免——已有等价能力，强行装配产生双重编排。

## 已修复：C 组（一致性缺陷，含 C-1/C-2/C-3）

### C-1: trace 多处断链（已修）
联邦出站注入 traceparent（`async_subagents.py` + `zhiku_tools.py`）；agent_server 入站提取+use_context（`routes.py`）；knowledge-service 入站提取（`query_router.py` /query + /api/v1/retrieve）。

### C-2: 契约无 version 字段（已修）
`shared_schemas.query` QueryRequest/QueryResponse 新增 `version` 字段（缺省 "1.0"，向后兼容），导出 `CONTRACT_VERSION`。

### C-3: 全仓 httpx client 不复用（已修）
agent_server `capabilities.py` + 联邦 `async_subagents.py` + `zhiku_tools.py` 改为进程级共享 client（连接池复用）。

### C-4: deterministic vs agentic 错误处理漂移
deterministic 异常炸断 SSE（无 error 事件），agentic 有完整 error 事件。
**修复方向**：deterministic `execute` 加 try/except，异常时 yield `StreamEvent(type="error")`。

### C-5: 无 recursion_limit
全仓库无 `recursion_limit` 配置，依赖框架默认值。
**修复方向**：联邦 `create_deep_agent` + `_get_local_agent` 配置 `recursion_limit`。

### C-6: 路由歧义
exhibition `select_skill` 静默落默认；联邦路由全 LLM 无规则兜底；`skill_router.py` 门禁未接线（死代码）。
**修复方向**：select_skill 未知 skill 返回错误而非静默默认；联邦加规则路由兜底；评估 skill_router.py 是否接线或删除。

### C-7: SQL 元知识跨租户
`schema_store.py:43-48` 的 `vector_search` 无 workspace 过滤，`sql_ddl` / `sql_docs` / `sql_examples` 表无 tenant 列。
**修复方向**：加 workspace 列 + WHERE 过滤。

### C-8: knowledge `/api/v1/retrieve` 无租户
`RetrieveRequest` 无 `tenant_id` 字段，`node_search_embedding` 在 tenant 为空时全库检索。
**修复方向**：`RetrieveRequest` 加 `tenant_id` 字段 + 透传到检索链路。

### C-9: health_check 404 误判
`health_check.py:28` 的 `status_code == 200` 为 False 时直接 return False，不进入 fallback 分支。
**修复方向**：改为 `if resp.status_code == 200: return True` + fall through to fallback。

### C-10: 默认端口冲突
agent_server / federation / nl2sql / knowledge 默认均为 8000。
**修复方向**：各服务默认端口错开。

### C-11: singleflight 互斥失效
`singleflight.py:55` 的 `_locks.pop(key, None)` 在等待者仍持旧 lock 引用时移除，可同时执行 fn。
**修复方向**：延迟 pop 或用 reference counting。

### C-12: sandbox env 泄漏
`sandbox.py:200` subprocess 后端继承宿主全部环境变量（含 LLM_API_KEY 等）。
**修复方向**：传 `env={}` 或白名单过滤。

### C-13: 健康探活标记对已构造 subagent 失效
`mark_unhealthy` 替换 frozen dataclass，但 `DelegatingSubAgent` 构造时捕获旧引用。
**修复方向**：`DelegatingSubAgent._svc` 改为动态查 `_subservices[key]`，或 `SubserviceConfig` 改为 mutable。

### C-14: `/api/task` 无超时 + 异常静默 + semaphore 泄漏
`server.py:214-225` 的 fire-and-forget 无 wall-clock 超时，异常不读，semaphore 槽位可泄漏。
**修复方向**：加 `asyncio.wait_for` + 读 `task.exception()` + semaphore 超时释放。

## 验证结果

| 包 | 测试结果 |
|---|---------|
| agent-runtime | 523 passed |
| agent_server + 根 | 440 passed, 15 skipped |
| knowledge-service | 230 passed, 13 skipped |
| federation | 134 passed |
| lint | All checks passed |
