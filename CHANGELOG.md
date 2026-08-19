# Changelog

本仓库为 uv workspace monorepo。**唯一受支持的安装/运行入口是根 `uv.lock` + `uv sync`**，子包不再维护独立 `uv.lock`（见 v2 修复 #14）。

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


