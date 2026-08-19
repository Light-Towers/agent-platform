# 架构边界建议：app/ 与 agent_federation/ 双平台

> 调研日期：2026-08-15
> 范围：仅梳理职责边界，**未改动任何代码**。
> 结论：两者是真正平行的独立可部署服务，零代码耦合，**无需合并**；仅需标注一处共享契约不对称（shared-schemas 采用度差异）。

## 1. 一句话定位

- `app/`：**单进程 Supervisor 平台**（进程内 StateGraph，路由/子能力/会话协调/准入/回退同一进程）
- `agent_federation/`：**联邦网关编排系统**（独立 HTTP 网关层 + 主管 Agent，通过 Agent Protocol 把子能力委派给远程子服务）

AGENTS.md 原文："根 `app/` 是一套单进程 Supervisor 平台；`agent_federation/` 是并行的联邦网关编排系统（两者非上下级）。"——调研印证此描述准确。

## 2. 零代码耦合（已确认）

- `agent_federation/` 下 `from app.` / `import app.` → **0 命中**
- `app/` 下 `from agent_federation.` / `import agent_federation.` → **0 命中**
- 两者均不启动/import 对方，通过 HTTP + 各子服务（kefu/wenda/zhiku）解耦。

> 易混提示：`zhanggui-zhiku/app/` 是 zhanggui 子项目内部包，与根 `app/`（统一平台）**不是同一个包**，勿误判为双向依赖。

## 3. 能力对比

| 能力 | `app/`（证据） | `agent_federation/`（证据） |
|------|------|------|
| 顶层 HTTP API | ✅ `applications/agent_server/main.py:152` FastAPI；`applications/agent_server/api/routes.py` | ✅ `agent_federation/api/server.py:79` FastAPI（标题 "DeepAgents API"） |
| Agent 编排 | ✅ `applications/agent_server/agent/graph.py:11,137` `StateGraph` + `build_graph()`（route→capability→synthesize） | ✅ `agent_federation/agent/main_agent.py:11,118` `create_deep_agent()`，主管 Agent 委派 SubAgent |
| 子能力 | search/rag/sql/mcp（进程内节点 `applications/agent_server/subagents/*`） | 3 子 Agent：network_search/database_query/knowledge_base；远程模式经 `async_subagents.py` 委派 wenda/zhiku/kefu |
| 网关/协调层 | 进程内意图路由 `applications/agent_server/agent/router.py`；`infra/coordinator.py`、`admission.py`、`revert.py` | 独立网关层 `agent_federation/api/server.py` + `gateway/`（input_guard/output_guard/rate_limit/gray）+ `agent/intent/` + `agent/rewrite/` + `agent/cache/` |
| 配置 | `applications/agent_server/config.py` pydantic-settings `Settings` | `agent_federation/agent/config.py` dataclass + dotenv；另有 YAML prompts |
| 端点 | `/query`(SSE)、`/health`、`/import`、`/sql/train`、`/session/revert` | `/api/task`、`/api/upload`、`/ws/{thread_id}`、`/health`；对子服务走 `/invoke`、`/api/messages` |

## 4. 共享内核采用度（**唯一不对称点**）

两者都依赖 `agent-core`（运行时内核）：
- `agent_federation/` 引用 `agent_core` 24 处（logging/tracing/guardrails 等）
- `app/` 引用 `agent_core` 7 处

但 `shared-schemas`（联邦契约）采用度**不对称**：
- `app/` **直接 import** `shared_schemas`：`applications/agent_server/config.py:5`、`applications/agent_server/schemas.py:13-21,80`、`applications/agent_server/api/routes.py:40`
- `agent_federation/` **不直接 import** `shared_schemas`（0 命中）；它仅通过下游子服务（kefu/wenda/zhiku）间接消费 `QueryRequest/QueryResponse`

> 建议：agent_federation 的 `async_subagents._HttpSubAgent` 已在 POST 时用 `QueryRequest` 字段形态、消费 `QueryResponse`，但未复用 `shared_schemas` 类型。
> 后续可在 agent_federation 侧直接 import `shared_schemas` 做请求/响应断言，统一契约校验（低风险、可选）。

**更新（2026-08-16，优化 E / P4.1 已落地）**：上述建议已实施——
- `agent_federation/pyproject.toml` 补 `shared-schemas` 依赖；
- `async_subagents._HttpSubAgent.ainvoke` 对 dict 响应执行 `shared_schemas.QueryResponse(**data)` 断言（`SqlQueryResponse` 超集被安全吸收），断言失败抛 `ValueError`，并加 `E1_CONTRACT_ASSERT` 灰度开关（S-1）；
- 现 agent_federation 已**直接 import** `shared_schemas`（契约采用度不对称已消除）。详见 `docs/plan-e-dual-track-convergence.md`。

## 5. 部署形态

- 根 `docker-compose.yml`：仅编排 `agent-platform`（即 `app/`，:8000）+ postgres。**不含 agent_federation**。
- `agent_federation/docker-compose.yml`：独立编排 agent_federation（:8000）+ mysql + langfuse/clickhouse/minio/valkey 全套可观测栈。**不含 app**。
- 两者各自独立 compose，印证"并行、非上下级、可独立部署"。

## 6. 行动建议

| 优先级 | 项 | 动作 | 是否改代码 |
|--------|----|------|-----------|
| 低 | shared-schemas 采用不对称 | agent_federation 侧 import `shared_schemas` 做契约断言 | 可选迭代 |
| 无需 | 合并双平台 | **不推荐**，两者零耦合、部署独立，强行合并破坏可独立演进能力 | 否 |
| 无需 | 删除任一平台 | **不推荐**，app 是统一平台主入口、agent_federation 是联邦网关，均为合法产品形态 | 否 |
| 建议 | 文档固化边界 | 本文件即固化证据；AGENTS.md/README 描述已准确，无需改 | 否 |

## 7. 一句话结论

`app/` 是单进程 Supervisor 平台，`agent_federation/` 是联邦网关编排系统，二者**平行、零代码耦合、可独立部署**。
当前边界已清晰且文档描述准确，**无需架构调整**；仅登记「shared-schemas 在 agent_federation 侧未直接复用」为可选的契约统一技术债。
