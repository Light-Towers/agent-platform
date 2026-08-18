# 优化 E：双轨编排收敛 — 专项规划（已评审，实施中）

> 状态：规划已按独立审核修订，P4.1~P4.3 全部实施完成（见顶部实施记录）
> 关联：`docs/architecture-improvement-plan.md` §2 优化 E / §4 路线图 P4
> 调研依据：`docs/architecture-boundary-app-vs-deepagents.md` + 本轮 `app/` 与 `deepagents/` 双轨代码调研
> 上游约束：`agent-core` 是 `reliable-agent` 哲学落地，零依赖铁律不可逾越（护栏清单第 1 条）
> 审核修订记录（2026-08-16）：依据独立源码核对，采纳 B-1 / M-1~M-5 / S-1~S-5，逐项修正如下。
> 实施记录（2026-08-16）：P4.1~P4.3 已全部落地并通过单测门禁（deepagents unit 44 passed；app 根 59 passed）。
>   - P4.1：deepagents/pyproject.toml 补 `shared-schemas` 依赖；`async_subagents._HttpSubAgent.ainvoke` 接入 `QueryResponse(**data)` 断言 + `E1_CONTRACT_ASSERT` 灰度开关；新增 `tests/unit/test_async_subagents_contract.py`(5)。
>   - P4.2：deepagents/pyproject.toml 补 `sqlglot`；新增 `tools/sql_guard.py` 薄封装委托 `agent_core.sql.guard(dialect="mysql")` + `USE_CORE_GUARD` 回滚开关；`db_tools.execute_sql_query` 改用薄封装；新增 `tests/unit/test_sql_guard_mysql.py`(7)，`sql_validation` 回归 18 维持。
>   - P4.3：新增 `agent_core/memory/backend.py`（仅 `MemoryBackend` Protocol 签名，零依赖）；`agent_core/memory/__init__.py` 导出并标注与 `ConversationMemory` 正交；`app/memory/memory_backend.py` 经优化 H 重写为**类型化记忆门面**（含 `MemoryBackend` 语义契约的本地实现），协议下沉目标已达成（内核为唯一真相源），re-export 形态随这次重写调整，记录形态过期已勘误（2026-08-18）。

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
| 远程治理 | 无（MCP 为进程内 client） | 在 `tools/zhiku_tools.py`（429 限流识别 + 健康探活降级）+ `tools/db_tools.py`/`tools/tavily_tool` 重试；`async_subagents.py` 仅是 **httpx/AsyncSubAgent 的薄封装门面**，本身不含限流逻辑（审核 M-4 纠正） |
| 合规外壳 | admission/coordinator/revert/PG checkpoint/SSE 均有 | 无（WS 而非 SSE） |

**共享内核复用点（已落地）**：输入护栏 `agent_core.guardrails.input_guard`（A 直接 import，B 经 `gateway/input_guard.py` re-export）；熔断 `agent_core.resilience`（A 显式，B 用 tenacity）；语义缓存均复用 `agent_core.cache.CacheStats`。

**审计锚点（审核 M-4 纠正）**：B 侧远程治理实际落在各 tool 内——`zhiku_tools.py:112` 识别 `429` 并回报 `Retry-After`；`zhiku_tools.check_zhiku_health()` 做启动期健康探活与乐观降级。E 收敛若涉及治理，应以这些 tool 为锚点，而非 `async_subagents.py`。

## 2. 可收敛项（低风险，建议落地）

### E-1 联邦契约对齐：`shared_schemas` 断言（P4.1，低风险）✅ 已实施

**前置（审核 B-1）**：`deepagents/pyproject.toml` 原**未声明 `shared-schemas` 依赖**（uv workspace 把它列为 member 但未加入 dependencies）。已补 `"shared-schemas"` 到 dependencies，使 B 侧 import 在依赖解析层成立。

- **现状**：`deepagents/agent/async_subagents.py:46` 的 `_HttpSubAgent.ainvoke` 按字段形态消费响应，**未复用 `shared_schemas` 类型**；wenda `/api/query` 实际返回 `SqlQueryResponse`（`QueryResponse` 子类，含 `sql/error`），kefu `/invoke` 返回 `QueryResponse`。
- **方案（审核 M-1 修正）**：`shared_schemas` 仅定义 `QueryRequest/QueryData/QueryResponse`（`shared_schemas/query.py`），**无 `SqlQueryResponse`**（该类型属 wenda 私有扩展）。故断言统一用 `shared_schemas.QueryResponse(**data)` 校验——`SqlQueryResponse` 字段超集可被 `QueryResponse` 安全吸收（额外字段被忽略），无需新增类型。
- **兼容性**：纯新增断言，远程调用协议不变；B 侧仍不直接依赖 app。
- **实施结果**：`_HttpSubAgent.ainvoke` 在 `data` 为 dict 时执行 `QueryResponse(**data)` 校验，校验失败抛 `ValueError`（含服务名 + 原始键），不再静默 `str(data)`；并补充 `tests/unit/test_async_subagents_contract.py` 覆盖通过/失败路径。
- **收益**：消除 `shared_schemas` 采用不对称（边界文档 §4 已登记为"低优先级可选迭代"）。

### E-2 SQL 守卫统一评估（P4.2，中风险，可选）
- **现状**：A 用 `agent_core.sql.guard.validate_sql`（sqlglot，支持 PG/sqlite）；B 用 `deepagents/tools/sql_validation.py`（sqlparse，走 MySQL wenda）。
- **方案（审核 M-2 修正）**：`agent_core.sql.guard.validate_sql(sql, dialect, max_rows)` **已支持 `dialect` 参数透传**（`guard.py:34` `sqlglot.parse(cleaned, read=dialect)`），`app/sql/guard.py` 也已支持 `mysql` 方言。故**不存在"需建方言分支"**——直接传 `dialect="mysql"` 即可，B 改为委托内核 guard 时无需新增分支。
- **风险**：sqlglot 与 sqlparse 对 MySQL 方言解析细节可能有边角差异；B 当前 `sql_validation` 还做了 `_ensure_limit`（无 LIMIT 时补 `LIMIT 100`）和标识符白名单，委托内核时需保留 LIMIT 兜底语义。
- **前置**：先补充 B 侧 SQL 守卫回归单测（当前 `sql_validation.py` 有纯函数但 `db_tools` 调用处缺用例）——注意用例数应为 **18**（审核 M-3 纠正：原审核误计为 14）。
- **实施计划**：`deepagents/pyproject.toml` 加 `sqlglot` 依赖 → 新增 `deepagents/tools/sql_guard.py` 薄封装委托 `agent_core.sql.guard`（传 `dialect="mysql"`，保留 LIMIT 兜底）→ `db_tools` 改用薄封装 → 跑 18 例回归 + 新增 `test_sql_guard_mysql.py`（含一条 `SELECT ... LIMIT` 与一条被禁 DML 用例）。
- **收益**：统一 SQL 合规硬约束（护栏清单第 2 条），内核为唯一真相源。若 sqlglot 边角差异不可接受，保留 B 独立守卫并文档记录，不强行统一。

### E-3 长期记忆内核对齐（P4.3，可选）
- **现状**：A 有 pgvector 长期记忆（`app/memory/memory_backend.py:24` 的 `MemoryBackend` Protocol + `PgVectorMemoryBackend`/`CompositeMemoryBackend`）；B 无进程内长期记忆。
- **方案（审核 M-5 修正）**：注意 `agent_core/memory/base.py` **已存在另一套协议** `ConversationMemory`（最小接口 `save`/`get_recent`/`clear`/`update`，宿主无关、零第三方依赖）。`app` 的 `MemoryBackend` 是 **semantic recall 语义**（`recall`/`remember`，耦合 `app.infra` pgvector），与 `ConversationMemory` 意图不同，二者**不可直接互相替换**。
  - **协议下沉**：将 `MemoryBackend` Protocol（仅 Protocol 签名，不含 pgvector 实现）下沉到 `agent_core/memory/backend.py`，使内核成为跨轨语义记忆契约的唯一真相源；`app/memory/memory_backend.py` 改为 `from agent_core.memory.backend import MemoryBackend` re-export，实现仍留 app 侧（因耦合 app.infra）。
  - **区分记录**：在 `agent_core/memory/__init__.py` 显式注释 `ConversationMemory`（会话历史存储）与 `MemoryBackend`（语义长期记忆召回）是两套正交能力，避免未来误合并。
- **收益**：语义记忆后端成为跨轨可插拔契约；B 接入需改 `create_deep_agent` 的 memory 挂载，属 B 侧独立迭代，本期不强制。

### F 外壳基础设施化：自研外壳抽为双轨共享（P4.4，可选，承接 TB-13/AR-2 讨论）

> **来源**：用户决策——若将 `app` 的 5 段自研生产外壳（admission/coordinator/revert/SQL 双保险/SSE）补到 `deepagents`，会自然引出"那 `app` 的 LangGraph 逻辑是否还有意义"之问。本优化给出工程结论与落地路径。

**关键澄清（误区别）**：
- 这 5 段外壳**全是 `app` 自研程序逻辑，不是 LangGraph 独有的框架能力**。LangGraph 仅提供"持久化 checkpoint + 可重放执行"这一内核能力（且 DeepAgents 底层就是 LangGraph，同样可用）。
- 因此"在 deepagents 补外壳"= 把自研代码**搬家**，不是"换框架"。补完后两轨差异收敛为**纯编排风格差异**（确定性 DAG 路由 vs 涌现式委派）。

**结论（回答"app 的 LangGraph 逻辑是否还有意义"）**：
1. `app` 里**显式 `StateGraph` 编排（`build_graph`）** 在 deepagents 接管后可退役（被 `subagents + middleware` 风格吸收）。
2. **LangGraph 内核永远在**（DeepAgents 依赖它），"LangGraph 没意义"表述错误。
3. 外壳代码**搬家不消失**——是团队自研资产。

**正确收敛（不做全量迁移）**：把 5 段外壳**抽为独立可复用的横向基础设施**，而非"各写一份 / 搬家一份"。双轨共用同一套外壳代码，编排层各自保留。

| 外壳能力 | 抽离形态 | 双轨接入方式 |
|---|---|---|
| admission 排队 | `app/infra/admission.py` → 独立 `agent_core`/网关包 `AdmissionQueue` | A 直接 import；B 在 `api/server.py` 请求入口挂载 |
| 会话并发协调 | `app/infra/coordinator.py` → 独立 `SessionCoordinator` | A 直接 import；B 在 `server.py` per-session 互斥 |
| 状态回退 | `app/infra/revert.py` → 暴露 `revert(thread_id, checkpoint_id)` 接口 | A `/api/revert`；B 新增等价 `/api/revert`（复用同一 `RevertHandler`） |
| SQL 双保险 | `agent_core.sql.guard`（已下沉）+ 连接只读 | 双轨共用 `agent_core`，无需各写 |
| SSE 事件映射 | `app/api/routes.py` 的 SSE renderer → 独立 `sse.py` | A 直用；B 若需 SSE 复用 renderer（WS/SSE 协议差异需适配层） |

**边界约束（继承 §3）**：抽离后仍禁止"抽 app 节点为 deepagents subagent"或反向图重写（护栏 S-4）。外壳可共享，编排不可合并。

**收益**：消除双轨外壳重复维护（TB-13）；B 侧获得持久化 checkpoint/回退能力（AR-2/TB-10）；为未来"确定性路由 vs 涌现委派"主线决策扫清外壳障碍。

**风险**：抽离需保证 `app` 现有行为零回归（admission 崩溃恢复、coordinator 丢失唤醒竞态防护都需保留）；B 侧 `thread_id` 会话断裂**已于 2026-08-18 审查核销**（`api/auth.py:resolve_thread_id` 按密钥派生稳定 `thread_id`，见 improvement-plan TB-14 已落地）——此前登记的 `server.py:165` 重建 bug 已消解，以下顺序从 PG checkpoint 注入起步即可。

**实施计划（建议顺序）**：
1. ~~先修 `server.py:165` thread_id 会话断裂~~ ✅ 已修（见 TB-14 核销），无需重复投入。
2. PG checkpoint 注入 `main_agent.py:132`（ADR-0002 已规划，代码未落地）。
3. 抽 `AdmissionQueue`/`SessionCoordinator`/`RevertHandler` 为共享基础设施，A/B 双挂。
4. 补 B 侧 `/api/revert` 端点，复用 A 的 `RevertHandler`。

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

| 阶段 | 内容 | 回归范围 | 门禁 | 状态 |
|---|---|---|---|---|
| P4.1 | E-1：`shared_schemas` 断言接入 `async_subagents`（含 B-1 补依赖） | `async_subagents` 单测 | pytest + eval | ✅ 已实施 |
| P4.2 | E-2：SQL 守卫统一评估（加 sqlglot 依赖 → 委托 `agent_core.sql.guard(dialect="mysql")` → 18 例回归 + 新增 MySQL 单测） | `sql_validation`/`db_tools` 用例（18） | pytest + eval | ✅ 已实施 |
| P4.3 | E-3：`MemoryBackend` 协议下沉 `agent_core.memory/backend.py`（仅协议，实现留 app；区分 `ConversationMemory`） | memory backend 单测 | pytest | ✅ 已实施 |

> **不实施**：编排代码合并（A→B 或 B→A 的图重写）。该项影响面最大、需充分 eval，且会破坏 §3 硬约束；若未来确需，应单独立项并先补齐 §3 外壳的等价实现。

## 5. 风险与缓解（含审核 S 系列）

- **E-1 远程契约变更（S-1 灰度）**：仅新增断言，协议不变；用 mock 单测覆盖失败路径。建议以**开关** `E1_CONTRACT_ASSERT`（默认 `on`）控制，断言失败时若开关 off 则回退到原 `str(data)`/`dict` 规整，便于现网快速回滚（无需发版）。门禁：单测断言开关 on/off 两条路径。
- **E-2 方言误拒（S-2）**：先补 18 例 B 侧回归单测再替换；若 sqlglot 方言参数无法覆盖 MySQL 边角，保留 B 独立守卫并文档记录，不强行统一。回滚：薄封装 `sql_guard.py` 加 `USE_CORE_GUARD` 开关，off 时走原 `sql_validation.py`。
- **E-3 协议下沉耦合（S-3）**：仅下沉 Protocol 签名（留空 `...`），**不搬 pgvector 实现**（实现仍耦合 `app.infra`），避免内核违反零依赖铁律。回滚：`app/memory/memory_backend.py` 保留本地 `MemoryBackend` 副本兜底（开关切换 import 源）。
- **误把 E 解读为"合并双轨"（S-4）**：本规划明确收敛仅在共享内核/契约层；任何"抽 A 节点为 B subagent"的提议均违反 §3 硬约束，应驳回。
- **范围外声明（S-5）**：本专项**不**覆盖——① 编排代码合并；② B 侧强制接入 pgvector 长期记忆；③ kefu 返回符合性逐项核验（审核"待确认#1"，需独立子任务，本期不纳入）；④ `agent_core.cache` 以外缓存能力统一。上述均不在 P4.1~P4.3 门禁内。
- **eval 门禁**：P4 每阶段结束跑 `make eval`（12 golden）确认无回归；eval 需 LLM/服务可达，CI 不可达时本地人工验证。

## 6. 与既有路线图的衔接

- 本规划是 `architecture-improvement-plan.md` §2 优化 E / §4 P4 的**展开**，不修改原路线图（原路线图 P4 标注"独立专项，本轮不实施"仍成立——本规划即该专项的草案）。
- 优化 A/B/C/D（v2 已落地）为 E 提供了基础：`AgentState` Pydantic 化、护栏共享内核、memory backend 协议、workspace 统一——E 在其上做内核层不对称收敛，不再重复造轮子。

---

*生成依据：本轮对 `app/agent/graph.py`、`app/subagents/*`、`deepagents/agent/main_agent.py`、`deepagents/agent/async_subagents.py`、`deepagents/tools/sql_validation.py` 等的双轨代码调研 + `docs/architecture-boundary-app-vs-deepagents.md`。本规划已按独立源码审核（B-1/M-1~M-5/S-1~S-5）修订，P4.1~P4.3 已实施完成。*
