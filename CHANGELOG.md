# Changelog

本仓库为 uv workspace monorepo。**唯一受支持的安装/运行入口是根 `uv.lock` + `uv sync`**，子包不再维护独立 `uv.lock`（见 v2 修复 #14）。

## Plan-F Phase 3 联邦侧收尾（2026-08-19）—— 双轨真正闭环

- **`agent_federation/planners/agentic.py`**：新增 `AgenticPlanner.arun(question, workspace_id, runtime, main_agent=None) -> str`——与 `execute`（供 app SSE 产出 StreamEvent）并存；`async with runtime.skill_guard("agentic")` 包裹 `_execute_agent_core`，将组合治理（max_skill_depth/max_steps）落地联邦主链路；`main_agent` 透传保留动态 agent 选择能力（不进统一协议）。
- **`agent_federation/planners/__init__.py`**：新增 `get_planner_runtime()` 模块级单例（联邦无 FastAPI app.state 注入先例），治理参数取 `FED_MAX_SKILL_DEPTH` / `FED_MAX_STEPS`（默认 4/20，与 PlannerRuntime 默认及 app/config 对齐），`registry=None`（联邦 agentic 不查能力注册表）。
- **`agent_federation/agent/main_agent.py`**：`run_deep_agent` 把 `singleflight(_execute_agent_core, ...)` 改为 `singleflight(AgenticPlanner().arun, ..., get_planner_runtime(), selected_agent)`——保留 singleflight 缓存击穿防护 + 全部副作用链（guard/intent/cache/memory/monitor/remember_episodic/SemanticCache），仅「最终执行」委托给 Planner 协议 + 治理；eval/WS 的 monitor 事件契约零破坏。
- **Boundary**：`deep_agent` subagents 委派机制（`_build_subagents` / `create_deep_agent`）保持不动——Plan-F 目标是「编排收敛」而非「重写委派」，避免破坏现有行为。
- **测试**：扩 `tests/unit/test_agentic_planner.py`（arun 经治理复用 + main_agent 透传 + 步数超限抛 `SkillCompositionError`）；新增 `tests/unit/test_run_deep_agent_planner.py`（run_deep_agent 经 planner.arun 走通 + monitor 上报保留）；联邦 unit 81 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F 单 Runtime 多 Planner 启动（2026-08-19）

- **方案文档** `docs/plan-f-single-runtime-multi-planner.md`：双轨收敛共识落档——「单 Runtime + 多 Planner」取代 plan-e 的「收敛」表述。含 K1–K5 卡点修正、R0 控制权冲突风险、P1–P5 五个落地契约点、Phase 0–3 路线图。
- **`shared-schemas/shared_schemas/thread.py`**：统一线程状态契约 `ThreadState`（messages 序列化 dict + metadata 编排状态 + version）——双 Planner 共享 checkpoint 的状态兼容基础（契约点 P2）。
- **`agent-runtime/` 新包**（uv workspace 新成员）：运行时中间件层。首个迁移单元 = admission：`app/infra/admission.py` → `agent_runtime/admission.py`，`AdmissionDecision` 类型 → `agent_runtime/schemas.py`；`app/schemas.py` re-export 兼容旧引用，`app/main.py` 改从 `agent_runtime` 引用。
- **验证**：根 tests **261 passed**（排除 wenda/dialogue 既有环境缺失目录）；迁移相关 test_router + test_input_guard_graph 8 passed；`app.main` import ok。
- **Phase 0 完成（同日）**：剩余 8 个运行时模块全部迁入 `agent_runtime.*`——cache / circuit_breaker / coordinator（CoordinationDecision）/ revert（RevertResult）/ mcp_client（McpServerConfig/McpToolResult）/ otel / tracing / db。`app/schemas.py` 对 4 个运行时类型 re-export 兼容；`app/infra/` 9 模块全部删除，仅留空包占位（退役标记）。
  - **配置依赖倒置**：`db.init_pool(database_url, db_pool_max_size)` / `db.ensure_schema(pool, vector_dim)` / `tracing.get_langfuse_callbacks(public_key, secret_key, host)`——agent-runtime 零依赖 `app.config`，参数由 app lifespan / scripts 从 Settings 注入。
  - 调用点全量更新：app 内部 8 文件 + scripts 3 个 + tests 4 个，改从 `agent_runtime.*` 引用。
  - 验证：根 tests **261 passed（零回归）**，`app.main` import ok，lint 0 error。
- 不做（遵循不过度设计）：`db.py` 的 `SCHEMA_TEMPLATE` 已随迁移归位（建表职责属 agent-runtime 初始化）；联邦 3 个 unit error 为 `deepagents` 改名遗留（测试文件仍 import PyPI `deepagents` 包），与本变更无关。

## Plan-F Phase 1 能力层中立化（2026-08-19）

- **`agent-runtime/agent_runtime/capabilities/` 新包**：`Capability` + `CapabilityRegistry`（注册/发现/统一执行入口，超时边界收敛于 execute）+ 三执行器工厂——`as_function_capability`（进程内 async 函数）/ `as_agent_capability`（subagent dict → lazy `deepagents.create_deep_agent`，与联邦本地 fallback 同路径）/ `as_remote_capability`（远程子服务调用）。
- **`app/capabilities.py`**：装配 search/rag/sql/mcp 四能力为 function 型注册项（惰性单例）；`app/agent/graph.py` 四节点改经 `registry.execute(...)`——能力层中立化首个生产路径验证。
- **测试**：`tests/test_capability_registry.py` 7 例（注册/发现/重复注册/未知能力/超时/三执行器）；根 tests **268 passed**（261 基线 + 7 新增，零回归），lint 0 error。
- 不做（遵循不过度设计）：联邦 `main_agent.py` 委派路径未改（deep_agent subagents 机制属 Phase 2 Planner 协议切换范围）；`Capability.metadata` 仅留扩展位不预填；MCP 能力签名依赖 state+manager 以 kwargs 透传承载，不强行重构为 query 形态。

## Plan-F Phase 1.5 Skill 契约升级（2026-08-19）

- **`agent-runtime/agent_runtime/capabilities/registry.py`**：`CapabilityKind` 增 `WORKFLOW`；`Capability` 增 `input_schema` / `output_schema`（JSON Schema dict，可空）；新增 `to_tool_schema()`（供 Agent 工具描述生成 + 入参契约显式化）。
- **`capabilities/dag.py` 新建**：`as_dag_capability(...)` → kind=WORKFLOW，把确定性 DAG 执行器封装为可注册 Workflow Skill（Static DAG Executor，对应 §4.1）。
- **`app/capabilities.py`**：定义 query/rag/general_qa 四套 JSON Schema 契约；`build_registry(graph=None)` 注入 graph 时注册 `general_qa` Workflow Skill（graph.py **包装非删除**），`get_registry` 惰性单例。
- **测试**：`test_capability_registry.py` 扩至 13 例（schema 契约 + WORKFLOW + general_qa 装配），零回归。

## Plan-F Phase 3 单 Runtime 成型（2026-08-19）

- **`agent_runtime/planner/protocol.py`**：新增 `SkillCompositionError` + `PlannerRuntime.skill_guard`（max_skill_depth=4 / max_steps=20 / 循环检测），仅 agentic 组合路径使用。
- **`app/memory/thread_persist.py` 新建**：`read_thread_messages` / `append_thread`——经 checkpoint aget_tuple/aput 落消息历史（channel_versions 推进 + new_versions 落 blob；空 answer/no checkpointer/thread 间隔离均正确 noop）。
- **`app/api/routes.py`**：`/query` 切 Planner 主路径（`PlannerContext`→`plan`→`execute`→StreamEvent→SSE 映射）+ graph 兜底 + 历史写回 checkpointer；新增 `_stream_event` 统一出口。
- **`app/main.py` / `app/config.py`**：lifespan 装配 `registry` + `planner_runtime`；配置增 `max_skill_depth` / `max_steps`。
- **测试**：新增 `test_planner_governance.py`（6）/ `test_thread_persist.py`（6）；根 tests **全量回归 322 passed（零回归）**，lint 0 error。
- 不做（遵循不过度设计）：WS 出口统一延后（app 现仅 SSE）；`version`/`risk_level`/`policy` 元数据暂缓（单实例无多租户分级诉求）。

## v2 Resilience 收敛（2026-08-19）

- **`agent-core/agent_core/resilience.py` 新增 `retry_async`**：异步指数退避重试原语（`max_attempts` 含首次、退避 `base*factor**(n-1)`、`exceptions` 过滤、可注入 `sleep`、支持同步/异步 `on_retry` 回调），与同步 `retry` 语义对齐。
- **`agent_federation/agent/async_subagents.py`**：`DelegatingSubAgent.ainvoke` 手写重试循环 → 内核 `retry_async`（行为等价：`max_attempts=RETRIES+1`、退避 `base*2**attempt`、成功即 `record_success`+返回、全败计入熔断并走本地 fallback），消除手写指数退避样板。
- **测试**：`test_resilience.py` 新增 8 例；agent-core 全量 146 passed；federation 契约测试 8 passed；行为等价验证 4 场景（首次成功 / 失败 1 次后成功 / 全败走 fallback / 熔断短路）。

> 不做的（遵循不过度设计）：Resilience Policy 三件套组合对象（Retry+Timeout+CB+Fallback）当前无真实「嵌套组合」调用点，待出现第 3 个组合需求再提取；`app/rag/rerank.py` / `zhanggui-zhiku` 的重试带 HTTP status-code 语义（429/5xx 才重试），与内核「按异常类型」语义不同，强行替换属过度设计。

## v2 TB 核销（2026-08-19）

- **TB-11 第一步落地（配置体系盘点）**：`agent_federation/README.md` 环境变量表重写 + `.env.example` 以源码为真相源全量盘点 80+ 开关（含共享内核 `agent_core.memory.*` 11 项）。修正 `SUBAGENT_RETRY_BASE` 默认值偏差（1.0→0.5，与 `async_subagents.py:153` 一致）；移除源码中已不存在的过时 `MYSQL_POOL_RESET_SESSION`；补全缺失开关：`KEFU_SERVICE_URL`/`KEFU_USE_ADAPTER`/熔断 `CB_*`×5/缓存 `KB_VERSION_*`×3/`TENANT_ID`/`RAGFLOW_*`/`EMBEDDING_DIM`/`DEEPAGENTS_DB_POOL_MAX`/`DATABASE_URL`/`EMBEDDING_API_KEY`。
- **审查核销**：优化 H（ADR-0004 阶段 1~3 已下沉内核 `agent_core.memory.typed`，D1~D5 全落地）、TB-9（意图分类收口内核 `agent_core.intent.classify_intent`，`intent_bridge.py` 单一真源）、TB-10（联邦已挂 typed 长期记忆 + 内核 checkpointer 三态）、TB-12（两轨缓存均实现 `BaseSemanticCache` 统计接口）状态已在 `docs/architecture-improvement-plan.md` 登记核销。
- 不做（遵循不过度设计）：agent_federation 配置全量迁移 pydantic-settings 属大 churn 且无真实复用需求，保留为长期项（待出现第 3 个配置消费方）。

## v2 分支修复记录（2026-08-16）

### 安全 / 护栏
- **#1** `app/agent/graph.py`：输入护栏拦截改为短路（`route:"blocked"` → `END`），拦截文案不再被 `synthesize_node` 覆盖；拦截不进记忆，避免原文落库。
- **#2** `app/agent/graph.py`：脱敏文本写回 `state.question`，下游路由/记忆均使用脱敏内容。
- **#4** 新增 `tests/test_input_guard_graph.py`：护栏拦截短路 / 脱敏传播 / guard 关闭透传 3 例回归。

### 工程 / 配置
- **#3** `pyproject.toml`：`ruff.lint.select` 显式固化 `["E4","E7","E9","F","I"]`，避免默认 select 漂移关闭 isort。
- **#7** `deepagents/requirements.txt`：补 `-e ../shared-schemas` 与 `sqlglot>=25.0`（非 uv 用户备选安装）。
- **#9** 核验：`FallbackChatModel` 默认 `failure_threshold=3`，降级阈值正确。
- **#11** `docs/architecture-improvement-plan.md`：「核验维持现状」记录项；原登记优化 A/B 要点2（`_validate_state`/`guard_middleware`）未实施已过时，参见下方「双轨技术债收敛」更正。
- **#14** 删除 `zhanggui-zhiku/uv.lock`，统一到 workspace 根锁。

### 核验维持现状（非缺陷）
- **#5** 路由结构化输出恒绑主模型，但 `decide_route` 已有启发式兜底，不阻塞。
- **#6** fallback `stream` 重播缺陷，app 链路未用 stream，待启用时再修。
- **#8** SQL 守卫 `max_rows`（默认 100）为有意的防护上限，非缺陷。
- **#12** `make type` 为 ruff 别名，非缺陷。
- **#13** `rag_query` 优先走 `AsyncSubAgent`，httpx 仅兜底，影响窄。
- **#15** logger 命名已规范（`__name__` + 顶层 `agent_core`），非缺陷。

### P4 双轨收敛（先前提交）
- P4.1 `shared_schemas` 契约断言（`AsyncSubAgent` 返回 `QueryResponse`）。
- P4.2 SQL 守卫下沉 `agent_core`（`deepagents/tools/sql_guard.py` 委托内核）。
- P4.3 `MemoryBackend` Protocol 抽象（`agent_core.memory`）。

### 技术债 TB 闭环（2026-08-16）
- **TB-4** `agent-core/agent_core/cache/base.py`：新增 `BaseSemanticCache` Protocol + `build_cache_key` 纯函数（sha256 of `intent|rewritten_query|kb_versions|tenant_id|gray_pct`），`deepagents` 复用，消除本地缓存键实现分歧。
- **TB-5** 语义缓存键契约固化（随 TB-4 一并收敛）。
- **TB-6** `deepagents/agent/async_subagents.py`：新增 `_normalize_response` + `_E1_CONTENT_ASSERT`，kefu 契约双向核验（形状 + 内容非空）；`kefu-service` 显式 `fallback=False`。
- **TB-8** `eval/run_eval.py`：加 `--require-llm`（环境不可达 SKIP 退出码 2）、默认 `--fail-below 0.8`；`Makefile` 评测改直接路径 `eval/run_eval.py`（避开 deepagents 同名模块冲突）。
- **TB-7** `docker-compose.yml`：为 `agent-platform` 补 healthcheck（TB-7 端到端冒烟可判定就绪）；`Makefile` 增 `compose-smoke`（需 Docker）；`scripts/smoke_memory.py` 提供无 Docker 的等价内存模式预热冒烟；说明见 `docs/tb7-smoke.md`。
- **TB-1** `dialogue-framework/shared/llm/core_adapter.py`：新增 `LLMCoreClient`，把 agent_core `BaseLLMProvider`（工厂协议）桥接为 DF `BaseChatClient`（运行时协议）；`BaseChatClient` 标记 `@runtime_checkable`，docstring 明确两者互补不合并。`langchain_client.py` 标注其 `FallbackChatModel` 即内核协议实现。
- **TB-2** `dialogue-framework/core/tracker_memory.py`：新增 `TrackerConversationMemory`，实现 agent_core `ConversationMemory` 协议（save/get_recent/clear/update），把 user/assistant 消息落进 `Tracker.events`；`Tracker.to_conversation_memory()` 桥接挂载。`dialogue-framework/tests/test_tb_bridge.py` 覆盖两协议桥接（3 passed）。

> 红线：dialogue-framework 不合并 / 删除，仅做协议对齐桥接（TB-1/TB-2 均满足，未改动 DF 自有数据结构与对外接口）。
> 至此 TB-1~TB-8 全部闭环。

### 双轨技术债收敛（2026-08-16 后续，commit 2bd215c + a6108c7）
- **优化 A 要点2** `app/agent/state.py` + `graph.py`：`AgentState.route` 由裸 `str` 枚举化为 `Literal["search","rag","sql","direct","mcp","blocked"]`（与 `graph.py` 条件分支键一一对应，非法路由值由 Pydantic 即时拦截）；新增 `_validate_state()` 入口校验（非空 `question`），在 `route_node` 调用。`tests/test_agent_state.py` 增 3 例。
- **优化 B 要点2** `deepagents/gateway/guard_middleware.py`（新增）+ `deepagents/agent/main_agent.py`：新增 `GuardMiddleware(AgentMiddleware)`，在 `before_agent` 钩子对入口 user 文本做 PII 脱敏改写 + injection 拦截；`_build_middleware()` 按 `GUARD_ENABLED` 开关注入（带失败降级），deepagents 视图 agent 默认经输入护栏。`deepagents/tests/unit/test_guard_middleware.py` 增 5 例。
- **TB-4 key 闭环** `app/infra/cache.py`：`_cache_write` 的 `cache_key` 由明文 `question.strip().lower()` 改为内核 `build_cache_key(intent="", rewritten_query=...)`，与 deepagents 共用同一 hash 逻辑（lookup 端纯向量命中，不受影响）。
- **U-1 收敛** `app/schemas.py`：普查确认无生产客户端仍发旧名 `question`/`thread_id`（deepagents `run-all.py` 调 adapter `/query` 已用标准名 `query`），**彻底移除** `AliasChoices` 双写兼容，入站契约收敛为纯标准名 `query`/`session_id`；清理未使用 `AliasChoices` import。`tests/test_api_smoke.py`、`agent-core/tests/test_guardrails.py` 示例字段名同步改 `query`。内部 `AgentState.question` 为 graph state 字段，与入站契约无关，保持不动。
- **文档一致性** `docs/architecture-improvement-plan.md`：§6.1 TB-1/TB-2 标注为「已落地（桥接）」；§6.2 U-1 标注「已闭环」；优化 A/B 标题回升「✅ 已落地」；#11 勘误回填。


