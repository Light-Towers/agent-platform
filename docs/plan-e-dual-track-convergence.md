# 优化 E：双轨编排收敛 — 专项规划（草案，待评审）

> 状态：规划草案（非实施）
> 关联：`docs/architecture-improvement-plan.md` §2 优化 E / §4 路线图 P4
> 调研依据：`docs/architecture-boundary-app-vs-deepagents.md` + 本轮 `app/` 与 `deepagents/` 双轨代码调研
> 上游约束：`agent-core` 是 `reliable-agent` 哲学落地，零依赖铁律不可逾越（护栏清单第 1 条）

## 0. 结论先行

**双轨不应在编排层合并代码。** `app/`（单进程 Supervisor）与 `deepagents/`（联邦网关 + `create_deep_agent`）是两种合法产品形态，二者**零代码耦合**（互不包含 import），且已通过 `agent_core` 共享内核。

强行把 A 的节点抽成 B 的 subagent（或反之）会同时破坏：
- `app` 的合规外壳（admission 排队、session coordinator、revert、PG checkpoint、sqlglot 双保险、SSE 事件映射）；
- `deepagents` 的联邦远程治理（Agent Protocol 委派、429 限流、探活降级）。

**收敛的正确范围 = 共享内核层的不对称补齐 + 联邦契约对齐**，而非编排代码合并。这是低风险、可独立测试、且不触碰编排核心的路径。

## 1. 双轨现状（调研摘要）

| 维度 | 轨道 A `app/` | 轨道 B `deepagents/` |
|---|---|---|
| 形态 | 自研 LangGraph Supervisor（`graph.py:build_graph`） | `create_deep_agent(subagents=[...])`（`main_agent.py:118`） |
| 搜索 | `app/subagents/search.py:search_web`（Tavily + 熔断） | `network_search_agent` + `tools/tavily_tool` |
| RAG | `app/subagents/rag.py:rag_query`（自研 pgvector） | `knowledge_base_agent` + `tools/zhiku_tools`（HTTP 调 zhiku 服务） |
| SQL | `app/subagents/sql_agent.py:sql_query`（Vanna 管线 + `agent_core.sql.guard` sqlglot + 连接只读双保险） | `database_query_agent` + `tools/db_tools`（独立 `sql_validation.py` sqlparse） |
| 记忆 | `app/memory/longterm.py`（pgvector 长期记忆） | 仅 deepagents 内部 `InMemorySaver`，**无 pgvector 召回** |
| 远程 | 无（MCP 为进程内 client） | `async_subagents.py`（Agent Protocol + 429/探活治理，独有） |
| 合规外壳 | admission/coordinator/revert/PG checkpoint/SSE 均有 | 无（WS 而非 SSE） |

**共享内核复用点（已落地）**：输入护栏 `agent_core.guardrails.input_guard`（A 直接 import，B 经 `gateway/input_guard.py` re-export）；熔断 `agent_core.resilience`（A 显式，B 用 tenacity）；语义缓存均复用 `agent_core.cache.CacheStats`。

## 2. 可收敛项（低风险，建议落地）

### E-1 联邦契约对齐：`shared_schemas` 断言（P4.1，低风险）
- **现状**：`deepagents/agent/async_subagents.py:46` 的 `_HttpSubAgent.ainvoke` 按字段形态消费 `QueryResponse`/`SqlQueryResponse`，**未复用 `shared_schemas` 类型**。
- **方案**：在规整分支 `import shared_schemas.QueryResponse`（及 `SqlQueryResponse`），对响应做 `QueryResponse(**data)` 契约校验，失败抛结构化错误而非静默 `str(data)`。
- **兼容性**：纯新增断言，远程调用协议不变；B 侧仍不直接依赖 app。
- **测试边界**：`async_subagents` 单测（mock httpx 返回 dict，断言校验通过/失败路径）。
- **收益**：消除 `shared_schemas` 采用不对称（边界文档 §4 已登记为"低优先级可选迭代"）。

### E-2 SQL 守卫统一评估（P4.2，中风险，可选）
- **现状**：A 用 `agent_core.sql.guard.validate_sql`（sqlglot，支持 PG/sqlite）；B 用 `deepagents/tools/sql_validation.py`（sqlparse，走 MySQL wenda）。
- **方案**：评估将 B 的 `sql_validation.py` 改为委托 `agent_core.sql.guard`，但**需处理方言差异**（wenda 为 MySQL，A 的 guard 当前面向 PG/sqlite）。
- **风险**：方言不兼容可能导致 B 的合法 MySQL 语句被 A 的 guard 误拒；需建 MySQL 方言分支或确认 sqlglot 方言参数。
- **前置**：先补充 B 侧 SQL 守卫的回归单测（当前 `sql_validation.py` 有纯函数但 db_tools 调用处缺用例），再评估替换。
- **收益**：统一 SQL 合规硬约束（护栏清单第 2 条），但**非必须**——若方言成本过高，保留 B 独立守卫亦可，仅记录不对称。

### E-3 长期记忆内核对齐（P4.3，可选）
- **现状**：A 有 pgvector 长期记忆（`memory_backend.PgVectorMemoryBackend`）；B 无进程内长期记忆。
- **方案**：将 `app/memory/memory_backend.py` 的 `MemoryBackend` 协议下沉为 `agent_core.memory`（内核已有 memory 模块），供 B 侧未来按需复用；B 当前不强制接入。
- **收益**：记忆后端成为跨轨可插拔能力；但 B 接入需改 `create_deep_agent` 的 memory 挂载，属 B 侧独立迭代。

## 3. 不可收敛的硬约束（护栏，禁止触碰）

以下为 `app` 自研外壳，双轨收敛**必须保留**，不得为"统一"而删除或弱化：

1. `app/infra/admission.py` — PG 持久化排队 + 优先级调度（deepagents 无）。
2. `app/infra/coordinator.py` — 会话级并发协调（deepagents 无）。
3. `app/infra/revert.py` + `RevertHandler` — 会话回退。
4. `app/main.py` PG `AsyncPostgresSaver` checkpoint（deepagents 仅内存/sqlite）。
5. `agent_core.sql.guard` + 连接级只读**双保险**（sqlglot；deepagents 用较弱 sqlparse）。
6. `app/memory/longterm.py` pgvector 长期记忆（deepagents 无）。
7. `app/api/routes.py` SSE 事件映射（deepagents 用 WS，不兼容）。
8. `deepagents/agent/async_subagents.py` 联邦远程委派治理（重试/429/探活）—— 反向把 A 本地能力提升为远程 subagent 成本过高，不做。

## 4. 分阶段实施（每阶段独立可测，门禁 = `make test` + `make eval`）

| 阶段 | 内容 | 回归范围 | 门禁 |
|---|---|---|---|
| P4.1 | E-1：`shared_schemas` 断言接入 `async_subagents` | `async_subagents` 单测 | pytest + eval |
| P4.2 | E-2：SQL 守卫统一评估（先补 B 侧回归单测，再决定是否替换） | `sql_validation`/`db_tools` 用例 | pytest + eval |
| P4.3 | E-3：`MemoryBackend` 协议下沉 `agent_core.memory`（可选，B 不强制接入） | memory backend 单测 | pytest |

> **不实施**：编排代码合并（A→B 或 B→A 的图重写）。该项影响面最大、需充分 eval，且会破坏 §3 硬约束；若未来确需，应单独立项并先补齐 §3 外壳的等价实现。

## 5. 风险与缓解

- **E-1 远程契约变更**：仅新增断言，协议不变；用 mock 单测覆盖失败路径，不影响现网。
- **E-2 方言误拒**：先补 B 侧回归单测再替换；若 sqlglot 方言参数无法覆盖 MySQL，保留 B 独立守卫并文档记录，不强行统一。
- **误把 E 解读为"合并双轨"**：本规划明确收敛仅在共享内核/契约层；任何"抽 A 节点为 B subagent"的提议均违反 §3 硬约束，应驳回。
- **eval 门禁**：P4 每阶段结束跑 `make eval`（12 golden）确认无回归；eval 需 LLM/服务可达，CI 不可达时本地人工验证。

## 6. 与既有路线图的衔接

- 本规划是 `architecture-improvement-plan.md` §2 优化 E / §4 P4 的**展开**，不修改原路线图（原路线图 P4 标注"独立专项，本轮不实施"仍成立——本规划即该专项的草案）。
- 优化 A/B/C/D（v2 已落地）为 E 提供了基础：`AgentState` Pydantic 化、护栏共享内核、memory backend 协议、workspace 统一——E 在其上做内核层不对称收敛，不再重复造轮子。

---

*生成依据：本轮对 `app/agent/graph.py`、`app/subagents/*`、`deepagents/agent/main_agent.py`、`deepagents/agent/async_subagents.py`、`deepagents/tools/sql_validation.py` 等的双轨代码调研 + `docs/architecture-boundary-app-vs-deepagents.md`。本规划为草案，实施前需评审确认 P4.1~P4.3 范围。*
