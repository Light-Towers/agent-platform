# 架构边界建议：agent_server/ 与 agent_federation/ 双平台

> 调研日期：2026-08-15；**更新 2026-08-21**（Plan-F Phase 2 后耦合关系变更）
> 范围：仅梳理职责边界，**未改动任何代码**。
> 结论：两者是真正平行的独立可部署服务，通过 packages/ 共享内核与契约；
> **但 Plan-F Phase 2 后 agent_server 对 agent_federation 存在可选依赖（AgenticPlanner）**，
> 已显式声明为 `[project.optional-dependencies] agentic`。

## 1. 一句话定位

- `applications/agent_server/`：**单进程 Supervisor 平台**（进程内 StateGraph，路由/子能力/会话协调/准入/回退同一进程）
- `applications/agent_federation/`：**联邦网关编排系统**（独立 HTTP 网关层 + 主管 Agent，通过 Agent Protocol 把子能力委派给远程子服务）

AGENTS.md 原文：“根 `applications/agent_server/` 是一套单进程 Supervisor 平台；`applications/agent_federation/` 是并行的联邦网关编排系统（两者非上下级）。”——调研印证此描述准确。

## 2. 代码耦合（2026-08-21 更新）

- `agent_federation/` 下 `from agent_server.` / `import agent_server.` → **0 命中**
- `agent_server/` 下 `from agent_federation.` / `import agent_federation.` → **1 处**（`planners/__init__.py`，PLANNER=agentic 时 lazy import AgenticPlanner）
- 该依赖已显式声明为根 pyproject `[project.optional-dependencies] agentic = ["agent-federation-app"]`，
  安装方式：`uv sync --extra agentic`。未安装时 PLANNER=agentic 启动报明确 ImportError。
- 两者均不启动/import 对方的主进程，通过 HTTP + 各子服务（kefu/wenda/zhiku）解耦。

## 3. 能力对比

| 能力 | `agent_server/`（证据） | `agent_federation/`（证据） |
|------|------|------|
| 顶层 HTTP API | ✅ `applications/agent_server/main.py:152` FastAPI；`applications/agent_server/api/routes.py` | ✅ `applications/agent_federation/api/server.py:79` FastAPI（标题 "DeepAgents API"） |
| Agent 编排 | ✅ `applications/agent_server/agent/graph.py:11,137` `StateGraph` + `build_graph()`（route→capability→synthesize） | ✅ `applications/agent_federation/agent/main_agent.py:11,118` `create_deep_agent()`，主管 Agent 委派 SubAgent |
| 子能力 | search/rag/sql/mcp（进程内节点 `applications/agent_server/subagents/*`） | 3 子 Agent：network_search/database_query/knowledge_base；远程模式经 `async_subagents.py` 委派 wenda/zhiku/kefu |
| 网关/协调层 | 进程内意图路由 `applications/agent_server/agent/router.py`；`infra/coordinator.py`、`admission.py`、`revert.py` | 独立网关层 `applications/agent_federation/api/server.py` + `gateway/`（input_guard/output_guard/rate_limit/gray）+ `agent/intent/` + `agent/rewrite/` + `agent/cache/` |
| 配置 | `applications/agent_server/config.py` pydantic-settings `Settings` | `applications/agent_federation/agent/config.py` dataclass + dotenv；另有 YAML prompts |
| 端点 | `/query`(SSE)、`/health`、`/import`、`/sql/train`、`/session/revert` | `/api/task`、`/api/upload`、`/ws/{thread_id}`、`/health`；对子服务走 `/invoke`、`/api/messages` |

## 4. 共享内核采用度

两者都依赖 `agent-core`（运行时内核）：
- `applications/agent_federation/` 引用 `agent_core` 24 处（logging-tracing/guardrails 等）
- `applications/agent_server/` 引用 `agent_core` 7 处

但 `shared-schemas`（联邦契约）采用度**不对称**：
- `applications/agent_server/` **直接 import** `shared_schemas`：`applications/agent_server/config.py:5`、`applications/agent_server/schemas.py:13-21,80`、`applications/agent_server/api/routes.py:40`
- `applications/agent_federation/` **直接 import** `shared_schemas`（2026-08-16 优化 E / P4.1 已落地）

> 建议：agent_federation 的 `async_subagents._HttpSubAgent` 已在 POST 时用 `QueryRequest` 字段形态、消费 `QueryResponse`，且已直接 import `shared_schemas` 做请求/响应断言（契约采用度不对称已消除）。

**更新（2026-08-16，优化 E / P4.1 已落地）**：上述建议已实施——
- `applications/agent_federation/pyproject.toml` 补 `shared-schemas` 依赖；
- `async_subagents._HttpSubAgent.ainvoke` 对 dict 响应执行 `shared_schemas.QueryResponse(**data)` 断言（`SqlQueryResponse` 超集被安全吸收），断言失败抛 `ValueError`，并加 `E1_CONTRACT_ASSERT` 灰度开关（S-1）；
- 现 agent_federation 已**直接 import** `shared_schemas`（契约采用度不对称已消除）。详见 `docs/plan-e-dual-track-convergence.md`。

**更新（2026-08-21，Plan-F Phase 2 耦合变更）**：
- agent_server `planners/__init__.py` 在 PLANNER=agentic 时 lazy import `agent_federation.planners.agentic.AgenticPlanner`；
- 该依赖已显式声明为根 pyproject `[project.optional-dependencies] agentic = ["agent-federation-app"]`；
- 两者不再是「零代码耦合」，而是「单向可选依赖」（agent_server → agent_federation，仅 agentic 模式）；
- 默认 deterministic/graph/auto 模式下两者仍无运行时耦合。

## 5. 部署形态

- 根 `docker-compose.yml`：仅编排 `agent-platform`（即 `applications/agent_server/`，:8000）+ postgres。**不含 agent_federation**。
- `applications/agent_federation/docker-compose.yml`：独立编排 agent_federation（:8002）+ mysql + langfuse/clickhouse/minio/valkey 全套可观测栈。**不含 agent_server**。
- 两者各自独立 compose，印证“并行、非上下级、可独立部署”。

## 6. 行动建议

| 优先级 | 项 | 动作 | 是否改代码 |
|--------|----|------|-----------|
| 低 | shared-schemas 采用不对称 | ~~已消除（2026-08-16）~~ | 否 |
| 低 | agent_server → agent_federation 可选依赖 | ~~已显式声明（2026-08-21）~~ | 否 |
| 无需 | 合并双平台 | **不推荐**，两者可独立演进、可独立部署，强行合并破坏可独立演进能力 | 否 |
| 无需 | 删除任一平台 | **不推荐**，agent_server 是统一平台主入口、agent_federation 是联邦网关，均为合法产品形态 | 否 |
| 建议 | 文档固化边界 | 本文件即固化证据；AGENTS.md/README 描述已准确，无需改 | 否 |

## 7. 一句话结论

`applications/agent_server/` 是单进程 Supervisor 平台，`applications/agent_federation/` 是联邦网关编排系统，二者**平行、可独立部署**。
Plan-F Phase 2 后 agent_server 对 agent_federation 存在**单向可选依赖**（PLANNER=agentic 时 lazy import AgenticPlanner），已显式声明为 `[project.optional-dependencies] agentic`。
默认模式下两者无运行时耦合，边界清晰。
