# 架构优化借鉴方案（基于开源标杆调研）

> 状态：提案（待评审）
> 关联文档：`docs/competitive-landscape.md`（对标调研）、`docs/architecture-boundary-app-vs-deepagents.md`
> 调研来源：LangChain(144k★)、Dify(152k★)、AutoGen(60k★)、CrewAI(57k★)、OpenAI Agents SDK(29k★)、DeepAgents(langchain-ai)
> 上游内核蓝本：[Light-Towers/reliable-agent](https://github.com/Light-Towers/reliable-agent)

## 0. 背景与目标

当前 `agent-platform` 已实现 LangChain/LangGraph 重度使用，并在 `deepagents/` 视图直接站在 DeepAgent 库（`create_deep_agent`）之上。本轮调研确认：项目在**内核分层零耦合**（`agent-core`/`shared-schemas`）、**extras 隔离重依赖**（`sql`/`mcp`/`pdf`/`otel`）上已对齐开源最佳实践。

### 0.1 上游内核蓝本：`reliable-agent`

`agent-core` 并非从零发明，而是受 GitHub 开源包 [Light-Towers/reliable-agent](https://github.com/Light-Towers/reliable-agent)（MIT，框架无关的 LLM/Agent 生产可靠性原语）启发/改写后的**本项目落地版**。两者组件一一映射、设计铁律一致：

| reliable-agent 组件 | agent-core 实现 | 重合度 |
|---|---|---|
| `tracing`（OTel 风格链路，零依赖可跑） | `agent_core.tracing` | 等价 |
| `eval.metrics`（Recall@k/MRR/NDCG 纯函数） | `agent_core.metrics.retrieval` | 等价 |
| `guardrails`（auth/ratelimit/web 中间件） | `agent_core.guardrails` | 等价 |
| `llm_client`（多模型 Provider 注册表） | `agent_core.llm` | 等价 |
| `memory`（Mongo+透传） | `agent_core.memory` | 等价 |
| `tool_registry`（`guarded_invoke`+MCP 隔离降级） | `agent_core.tools` | 等价 |
| `resilience`（CircuitBreaker/retry/timeout） | `agent_core.resilience` | 等价 |

关键事实：
- **不是 pip 依赖**：`agent-core/pyproject.toml` 的 `dependencies=[]`，全仓库 `.toml` 无任何 `reliable-agent` 引用 —— 项目是**自研实现等价内核**，而非直接 `pip install` 该包。
- **设计铁律同源**：`reliable-agent` 的"框架无关、core 绝不 import langgraph/宿主应用、重依赖全部 extra+lazy import、仅 stdlib 可 import"原则，与 `agent-core/README.md` 的"设计铁律"逐字对应。
- **对优化的含义**：`agent-core` 已是 `reliable-agent` 哲学的落地，护城河在**可靠性内核**而非编排框架；任何优化（含优化 E 双轨收敛）都必须保留 `reliable-agent` 式零依赖内核契约（见 §3 护栏清单第 1 条）。v2 新增的 `fallback_lc.py` 正是该哲学在 LangChain 侧的薄适配（保持 `BaseChatModel` 兼容 + 复用 `FallbackChatModel` 降级语义，不破坏内核零依赖）。

但存在 5 处与高 star 项目共识的差距，且 `app/` 与 `deepagents/` 双轨编排并存。本方案**不推翻重写**，而是提出**分阶段、低风险、可独立测试**的优化，每项均保留现有内部契约兼容，避免全局回归。

## 1. 现状定位（当前架构快照）

| 维度 | 现状 | 文件锚点 |
|---|---|---|
| 状态定义 | `AgentState(BaseModel)`，**Pydantic 运行时校验**（优化 A 已落地） | `app/agent/state.py:21` |
| 输入护栏 | `guard_input()` 已下沉为 `agent_core.guardrails.input_guard` 共享内核，deepagents/app 双视图统一入口 | `agent_core/guardrails/input_guard.py` |
| 长期记忆 | `MemoryBackend` 协议 + `PgVectorMemoryBackend`（默认）+ `CompositeMemoryBackend` 预留；门面 `longterm.py` | `app/memory/memory_backend.py` |
| 依赖管理 | `uv workspace` 成员声明已启用（根 `[tool.uv.workspace]` + 各子包去重 sources），monorepo 统一解析 | `pyproject.toml:65` |
| 工程门禁 | `Makefile`（make install/lint/test/eval/ci）+ 全仓 ruff 绿 + pytest 门禁可用 | `Makefile` |
| 编排 | `app/` 自研 Supervisor 图 vs `deepagents/` `create_deep_agent`，双轨（优化 E 已落地，内核/契约层收敛，非合并代码） | `app/agent/graph.py:33` vs `deepagents/agent/main_agent.py:118` |

## 2. 优化项清单（按优先级与风险分级）

### 优化 A：`AgentState` 升级为 Pydantic BaseModel（中优先级 / 低-中风险） ◐ 部分落地（要点1 已完成，要点2 未实施）

- **借鉴来源**：CrewAI Flows 用 `class MarketState(BaseModel)` 在 Flow 步骤间结构化传递状态；OpenAI Agents SDK 全链路 Pydantic 模型校验。
- **当前差距**：`TypedDict` 只在静态类型检查期生效，运行时节点写入脏字段/类型错误只能等下游崩溃。
- **方案要点**：
  1. 将 `app/agent/state.py` 的 `AgentState` 改为 `pydantic.BaseModel`，保留 `messages: Annotated[list, add_messages]` 的 reducer 语义（Pydantic 兼容 `Annotated`）。
  2. （未实施）新增节点入口处的 `_validate_state()` 校验函数，对 `route` 枚举、必填字段做断言。`AgentState` 虽已 Pydantic 化，但尚未引入入口校验函数（`route` 仍为 `str` 非枚举）。
  3. 保留 `total=False` 等价性：用 `Field(default=None)` 表达可选字段。
- **兼容性**：LangGraph `StateGraph` 同时支持 TypedDict 与 Pydantic model 作为 state schema，无需改动 `graph.py` 的节点签名。
- **测试边界**：仅需回归 `app/agent/graph.py` 全流程 + `tests/` 中 state 相关用例（约 40 用例中的 state 读写部分）。
- **收益**：节点边界脏 state 即时暴露，减少"脏数据穿透到 synthesize"类偶发 bug。

### 优化 B：输入护栏下沉为共享内核 + 双视图统一入口（中优先级 / 中风险） ◐ 部分落地（要点1/3 已完成，要点2 未实施）

- **借鉴来源**：OpenAI Agents SDK 将 Guardrails 作为 Agent 一等公民；DeepAgents 用 `RubricMiddleware`/`TodoListMiddleware` 栈式横切。
- **当前差距**：`guard_input()` 是外层包裹，与编排解耦但无法作为反思/规划链的一环，且 `app/` 视图完全无护栏。
- **方案要点**：
  1. **保留** `deepagents/gateway/input_guard.py` 的全部检测逻辑（`detect_pii`/`redact_pii`/`detect_injection`/`guard_input`），不重写规则。
  2. （未实施）新增薄适配层 `deepagents/gateway/guard_middleware.py`：将 `guard_input` 包装为 DeepAgent Middleware（`@middleware`/`BaseMiddleware`），挂到 `create_deep_agent(middleware=[..., GuardMiddleware])`（`main_agent.py:63`）。当前 `guard_input` 仅在 `app/route_node` 与 `deepagents` 网关入口直接调用，未封装为 Middleware 栈。
  3. `app/` 视图在 `route_node` 前插入同一 `guard_input` 调用（单函数复用，非重写）。
- **兼容性**：检测函数签名与返回字典不变；仅新增包装，旧调用方（`deepagents` 网关入口）行为不变。
- **测试边界**：回归 `input_guard` 既有单测（若有）+ 新增 middleware 挂载冒烟；影响面限于入口链路，不触碰检索/生成。
- **收益**：护栏成为可插拔横切层，未来可叠加 `RubricMiddleware` 反思；双视图统一安全入口。

### 优化 C：长期记忆多后端路由（中优先级 / 中风险） ✅ 已落地

- **借鉴来源**：DeepAgents `CompositeBackend` 按路径把状态路由到耐久存储（文件/向量）。
- **当前差距**：`longterm.py` 仅单 pgvector 表，文件型/缓存型记忆无去处；写入只入 `memories` 表。
- **方案要点**：
  1. 在 `app/memory/` 新增 `memory_backend.py`：定义 `MemoryBackend` Protocol（`recall`/`remember`），保留现有 `PgVectorMemoryBackend`（即当前实现）为默认后端。
  2. 预留 `CompositeMemoryBackend`（按 `namespace` 字段路由到 pgvector / 本地文件 / 语义缓存），**首期只实现 pgvector 后端，复合路由留接口不启用**。
  3. `recall`/`remember` 对外签名不变，调用方（`graph.py:59,98`）零改动。
- **兼容性**：对外 API 完全向后兼容；复合后端为可选扩展，默认关闭。
- **测试边界**：回归 `app/memory/longterm.py` 既有行为 + 新增 backend 协议单测，不影响图执行。
- **收益**：为未来"对话摘要存文件、事实存向量"分层铺垫，且不破坏现有写链路。

### 优化 D：统一 `uv workspace` + `Makefile` 工程门禁（低优先级 / 低风险）

- **借鉴来源**：LangChain/CrewAI/DeepAgents 全部用 uv workspace + `Makefile` 统一任务。
- **当前差距**：根 `pyproject.toml` 用 `[tool.uv.sources]` editable 引用子包，但未声明完整 workspace；缺统一 `make lint/test/type/eval` 门禁。
- **方案要点**：
  1. 在各子包 `pyproject.toml` 补充 `[tool.uv.workspace]` 成员声明，根做 workspace root。
  2. 新增 `Makefile`：`make install`（uv sync）、`make lint`（ruff）、`make test`（pytest -q）、`make eval`（python -m eval.run_eval）、`make type`（可选 pyright/ty）。
  3. `make test` 串联现有 `pytest -q` 与 `eval/`，作为回归总闸。
- **兼容性**：纯工程脚手架，不改任何业务代码。
- **测试边界**：无需功能回归；仅验证 `make` 各目标可运行。
- **收益**：统一本地/CI 入口，降低新成员上手与回归执行成本。

### 优化 E：双轨编排收敛（高优先级 / 高风险，独立专项）

- **借鉴来源**：本项目 `deepagents/` 已验证 `create_deep_agent` 可用；CrewAI 双范式（Crews+Flows）说明"自主 vs 可控"可共存但需统一底座。
- **当前差距**：`app/` 自研 Supervisor 图与 `deepagents/` 应用层重复实现编排，技术栈分裂，维护双倍成本。**但调研确认双轨零代码耦合，且已通过 `agent_core` 共享内核**；重复主要在"应用层编排形态"而非"能力实现"。
- **收敛范围（基于调研修正方向）**：**不在编排层合并代码**——强行以 `create_deep_agent` 为底座重写 `app/graph.py` 会破坏 `app` 的 admission/coordinator/revert/PG checkpoint/sqlglot 双保险/SSE 外壳，且丢失 `deepagents` 的联邦远程治理。正确收敛在**共享内核层与联邦契约层**：
  1. `shared_schemas` 契约对齐：`deepagents/agent/async_subagents.py` 的远程响应接入 `QueryResponse` 断言（消除不对称）。
  2. SQL 守卫统一评估：`deepagents/tools/sql_validation.py`（sqlparse）与 `agent_core.sql.guard`（sqlglot）的方言兼容评估（可选）。
  3. `MemoryBackend` 协议下沉 `agent_core.memory`，供双轨复用（可选）。
- **必须保留**的自研外壳（硬约束，禁止为"统一"而弱化）：`app/main.py` 的 admission 排队、session coordinator、SSE 事件映射、语义缓存、`sqlglot` SQL 守卫、PG checkpoint、`gateway/input_guard.py` 合规护栏；`deepagents` 的联邦 remote subagent 委派治理（重试/429/健康检查）。
- **风险**：编排核心若误合并影响面最大；故收敛限定在内核/契约层，每阶段独立可测。
- **专项规划**：详见 `docs/plan-e-dual-track-convergence.md`（P4.1~P4.3 已实施，经独立审核修订后落地）。

## 3. 必须保留、不可替换的深度定制（护栏清单）

以下为项目护城河，任何优化均不得触碰：

1. **`agent-core` 内核契约**：`Tool` Protocol + `guarded_invoke` 超时隔离、`llm/providers` 注册表缓存、embedding 后端、tracing `_NoOpSpan` 降级铁律。刻意与 LangChain 解耦。该内核是 [reliable-agent](https://github.com/Light-Towers/reliable-agent) 哲学的落地版，零依赖铁律（core 绝不 import langgraph/宿主应用、重依赖全部 extra+lazy import）为不可逾越红线。
2. **`sqlglot` SQL 守卫**（`agent_core/sql/guard.py`）：强制 LIMIT/禁 DDL，合规硬约束。
3. **BGE-M3 双向量 + 本地稀疏向量生成器**（md5 稳定 id，`zhanggui-zhiku/lm/sparse_vectorizer.py:73`）：零依赖可复现硬约束。
4. **动态 TopK 断崖截断 + 索引版本 registry + eval 回填**（`zhanggui-zhiku/node_rerank.py:208`）：检索治理闭环。
5. **联邦网关 remote subagent 委派治理**（`tools/zhiku_tools.py:86` 重试/429）：平台级 SLA。
6. **PII 脱敏 + injection 检测 + 输出合规**（`gateway/input_guard.py`）：国产合规策略。

## 4. 实施路线图（分阶段，每阶段独立可测）

| 阶段 | 内容 | 回归范围 | 门禁 | 状态 |
|---|---|---|---|---|
| P0 | 优化 D（Makefile + uv workspace） | 无业务代码改动 | `make install/test` 通过 | ✅ 已落地（Makefile + workspace 成员声明，commit 163a6dc） |
| P1 | 优化 A（`AgentState` → Pydantic） | `app/agent/graph.py` + state 用例 | pytest + eval 全绿 | ✅ 已落地（commit f0a5f43） |
| P2 | 优化 B（护栏共享内核 + 双视图统一入口） | 入口链路 + input_guard 单测 | pytest + eval 全绿 | ✅ 已落地（commit a23755e） |
| P3 | 优化 C（memory backend 协议） | `app/memory/longterm.py` 行为 | 新增 backend 单测 + eval 全绿 | ✅ 已落地（commit dd51aa9） |
| P4（后置） | 优化 E（双轨收敛） | 内核/契约层 | 独立专项 + eval 充分验证 | ✅ P4.1~P4.3 已落地（shared_schemas 断言 + SQL 守卫统一 + MemoryBackend 下沉内核）；专项规划见 `docs/plan-e-dual-track-convergence.md` |

> P0~P3 均为**局部改动 + 向后兼容**，每阶段结束跑 `make test`（含 40 单测）与 `make eval`（12 golden）即可确认无回归。P4 为架构级，单独立项。

## 5. 风险与缓解

- **Pydantic state 与 LangGraph reducer 冲突**：`add_messages` 是 reducer 函数，Pydantic field 需验证其可承载；先在小图验证再全量。**已验证**：`tests/test_agent_state.py` 确认 Pydantic `AgentState` + `add_messages` 在真实 `StateGraph` 中正常累加。
- **middleware 包装改变调用时序**：`guard_input` 返回值字典结构保持不变，仅挂载位置变化；用现有网关单测覆盖。
- **uv workspace 破坏现有 editable 安装**：已在隔离分支验证 `uv lock` + `uv sync` 成功（255 包，含 zhanggui torch 重依赖），无破坏后合并（commit 163a6dc）。
- **回归验证总闸**：所有阶段以 `make test` + `make eval` 为强制门禁，未全绿不合并。

---

---

## 6. 待办与技术债登记（v2 之后）

> 本节登记 v2 路线图中**尚未实施**或**已识别但未纳入**的问题。按优先级/红线排序，每项标注来源与约束，避免遗留成隐性债务。

### 6.1 已识别技术债（建议后续迭代）

| 编号 | 问题 | 来源 | 风险 | 红线/约束 |
|---|---|---|---|---|
| TB-1 | **DF 双 LLM 协议冗余**：`dialogue_framework.shared.llm.base_client.BaseChatClient` 与 `agent_core.llm.providers.BaseLLMProvider` 签名不兼容、互不对接 | `architecture-boundary-agent-core-vs-dialogue-framework.md:63` | 低 | DF 弃用自有 `BaseChatClient`、对齐内核协议；**不合并/删除 dialogue-framework** |
| TB-2 | **DF 双 memory 抽象冗余**：`dialogue_framework.core.Tracker`（slots/events/stack）未使用 `agent_core.memory.ConversationMemory` | 同上:64 | 低 | DF `Tracker` 适配 `ConversationMemory`；不合并两包 |
| TB-3 | **uv workspace 环境脆弱**：根 `uv sync` 会卸载非根 member 包（实测卸载 24 包，含 deepagents-app），默认环境不含非根包依赖 | 实施过程实测 | 中（已缓解） | **已修复**：根因是 uv workspace 默认 `uv sync` 只装根包。固化约定为 `uv sync --all-packages --extra dev`（装全部 workspace 包 + dev 工具），单包测试用 `uv run --package <pkg> ...`；运行约定已写入 `README.md` uv workspace 段。裸 `uv sync` 仍会卸载非根包，勿直接使用 |
| TB-4 | **M5 语义缓存统一未落地**：`agent_core.cache` 已建 `CacheStats`/`build_cache_key` 单一真相，但 app(`PgSemanticCache`)/deepagents(`ValkeySemanticCache`) 尚未统一到 `BaseSemanticCache` 接口 | `m5-semantic-cache-plan.md`（纯草案，未实施） | 中 | ✅ 已落地（2026-08-16）：`agent_core.cache` 新增 `BaseSemanticCache` Protocol + 零依赖 `build_cache_key` 纯函数（单一真相）；deepagents `layers.py` 复用内核 `build_cache_key`（移除本地 hash 重复，I 规则清理 hashlib/json）；app `infra/cache.py` docstring 标注遵循协议、不跨后端共享数据。补 `agent-core/tests/test_cache_key.py`。遵循 §6 约束：仅统一接口与 key 构造，不跨后端共享缓存数据 |
| TB-5 | **deepagents 联邦契约统一（原 TODO）**：`shared_schemas` 在 deepagents 侧原未直接复用（仅 app 侧用），已在优化 E/P4.1 补齐断言——**已闭环**，此处仅作历史登记 | `architecture-boundary-app-vs-deepagents.md:69` | 已解决 | — |

### 6.2 范围外 / 未核验项（需独立子任务）

| 编号 | 问题 | 来源 | 说明 |
|---|---|---|---|
| TB-6 | **kefu 返回符合性逐项核验**：优化 E 仅对 `async_subagents` 加 `QueryResponse` 断言（消费侧），未反向核验 kefu `/invoke` 是否逐字段符合 `QueryResponse`（含 `fallback`/`error`/`sources` 字段形态） | `plan-e-dual-track-convergence.md:95` S-5③ | ✅ 已落地（2026-08-16）：逐项核验 kefu `/invoke` 返回的 `QueryResponse` 字段（answer/data.content.intent/source/trace_id/latency_ms/intent/fallback）均与 `shared_schemas.query.QueryResponse` 契约一致；发现并修复"形状合法但内容空洞"盲区——kefu 图未产出 response 时返回空 answer（契约通过但语义退化）。收口：① kefu `_run_kefu` 显式 `fallback=False` + 空 answer 日志告警；② 消费侧 `_HttpSubAgent` 抽出 `_normalize_response` 纯函数，新增 `E1_CONTENT_ASSERT` 内容断言（answer 非空，与形状断言分离可独立回滚）；③ 新增 `deepagents/tests/unit/test_async_subagents_contract.py` 中 3 例 TB-6 双向符合性测试（kefu 真实字段提取 / 空 answer 告警 / 开关 off）。字段形态结论：kefu 未传 `error`/`sources`（契约非必填，合法）；`fallback` 此前隐式默认，现显式 |
| TB-7 | **docker compose 端到端冒烟**：`docker-compose.yml` 已存在，但缺一键端到端冒烟验证 | `research-proposal.md:120` | 可选；需服务可达环境 |
| TB-8 | **eval 门禁 CI 化**：本地 `python -m eval.run_eval` 12/12 通过，但 eval 依赖 LLM/服务可达，CI 不可达时仅本地人工验证 | `architecture-improvement-plan.md:134` | 建议固化 CI 跳过策略 + 本地门禁约定 | ✅ 已落地（2026-08-16）：`run_eval.py` 加 `--require-llm`（环境不可达显式 SKIP 退出码 2，不假装通过）+ 默认 `--fail-below 0.8` 门禁阈值；Makefile `install` 改用 `--all-packages --extra dev`（TB-3 约定）、`eval` 改用**直接路径** `eval/run_eval.py`（避免命中 deepagents 同名模块）、新增 `eval-llm-required` target。`ci: lint test eval` 串联依赖 uv run 退出码透传（已验证）。ruff F821 对 `{args.fail_below:.0%}` 中文 f-string 误报，改用 `.format` 规避 |

### 6.3 说明

- TB-1/TB-2 是本次 v2"双轨收敛"的**延伸项**，按边界文档判定为低优先级后续技术债，**不应在 v2 强行收敛**（DF 仅包内自引用、强行合并违反红线）。
- TB-3 是**工程环境问题**，与代码正确性无关，但会误伤开发者环境，建议尽早固化运行约定。
- TB-4 是已规划未实施的**独立专项**（M5），与 E 平行，可单独排期。

*生成依据：v2 实施过程实测 + `docs/` 下各边界调研与专项规划文档登记的待办项汇总（2026-08-16）。*

---

## 7. v2 分支 15 条严格审核 — 修复登记（2026-08-16）

来源：用户派发三评审子代理产出的 15 条审核（MUST FIX #1 / SHOULD FIX #2-#10 / CONSIDER #11-#15），已逐条源码核验，14/15 成立（#13 影响面窄于报告，见下）。

### 7.1 本轮已修复（app 护栏组 + lint 固化）

| 编号 | 问题 | 核验结论 | 修复 | 状态 |
|---|---|---|---|---|
| #1 | app 护栏假拦截：`route_node` blocked 返 `route:"direct"` 无短路，`synthesize_node` 覆盖 `answer`，`remember()` 写原文进记忆 | 成立 | `graph.py`：`blocked` 返 `route:"blocked"` + `add_conditional_edges` 加 `blocked: END` 短路；answer 不再被覆盖；拦截不进 synthesize 故不 `remember` | ✅ 已修 |
| #2 | 脱敏未传播：`guard["redacted_text"]` 仅局部变量，未写回 `state.question` | 成立 | `graph.py`：正常路由返回加 `"question": question`（脱敏值）；下游路由/记忆均用脱敏文本 | ✅ 已修 |
| #3 | ruff 默认 `select=E4,E7,E9,F` 无 I 组，import 排序规则被静默关闭 | 成立 | `pyproject.toml [tool.ruff.lint]` 显式 `select=["E4","E7","E9","F","I"]` 固化规则集 | ✅ 已修 |
| #4 | app 护栏无回归测试 | 成立 | 新增 `tests/test_input_guard_graph.py`：拦截短路 / 脱敏传播 / guard 关闭透传（3 例） | ✅ 已修 |
| #9 | 降级阈值 `failure_threshold` 1→3 漂移 | 已自然满足 | `agent_core.llm.fallback.FallbackChatModel` 默认 `threshold=3`，`build_chat_model()` 未覆盖；无需改 | ✅ 核验通过 |

### 7.2 已核验、待排期（非本轮强制范围）

| 编号 | 问题 | 现状 | 建议 |
|---|---|---|---|
| #5 | fallback `bind_tools` 恒绑主模型，结构化输出不可降级 | v2 重构后 `FallbackChatModel` 仅 `with_structured_output`（亦恒绑 primary）；但 `decide_route` 已有 `try/except → heuristic_route` 兜底，主模型结构化失败不阻塞路由 | 维持现状：启发式兜底已覆盖，降级路由收益极低 |
| #6 | fallback `stream` 主模型异常后重播 fallback 全量，客户端收到重复 chunk | app 链路 `synthesize` 用 `ainvoke` 未用 stream，`FallbackChatModel.stream/astream` 无调用方 | 维持现状：潜在缺陷，待 streaming 启用时再修（缓冲已吐 chunk） |
| #7 | `requirements.txt` 未同步 `shared-schemas`/`sqlglot` | 根目录无 requirements.txt（uv workspace 管理）；`deepagents/requirements.txt` 漏列 `shared-schemas`/`sqlglot` | ✅ 已修：`deepagents/requirements.txt` 补 `-e ../shared-schemas` + `sqlglot>=25.0` |
| #8 | SQL 守卫 `LIMIT>100` 截断 + 文本重生成 | `agent_core.sql.guard` 的 `max_rows`（默认 100，`SQL_GUARD_MAX_ROWS` 可配）是**有意的防护上限**，防 `SELECT *` 拖垮 DB；截断后返回规整 SQL 是正常归一化 | 维持现状：安全设计，非缺陷 |
| #10 | 仅 workspace 安装 + 缺 CHANGELOG | 工程约定问题 | ✅ 已修：新增 `CHANGELOG.md`，明确 uv workspace 为唯一安装入口 |
| #11 | `_validate_state`/`guard_middleware` 文档提及但代码不存在 | 实为 §2 优化 A/B 要点2 规划项未实施；标题"✅已落地"误导 | ✅ 已勘误：要点2 标"（未实施）"，标题降为"◐部分落地" |
| #12 | `make type` 是 ruff 别名 | 非缺陷 | 无需修 |
| #13 | `rag_query` 端点 httpx 兜底 | 实际优先走 `AsyncSubAgent`，httpx 仅兜底且已收敛，影响窄于报告 | 维持现状 |
| #14 | `zhanggui-zhiku` 双 `uv.lock` | 子包独立 lock 与 workspace 根锁冲突 | ✅ 已修：删除 `zhanggui-zhiku/uv.lock`，统一根锁（`uv lock` 验证通过） |
| #15 | logger name 变更 | 核验：app 全量 `getLogger(__name__)` + 顶层 `agent_core` 命名已规范 | 无需修：非缺陷 |

*门禁：本轮修复后 `ruff check .` 全绿，`pytest tests/` 84 passed（含新增 3 例）。*
