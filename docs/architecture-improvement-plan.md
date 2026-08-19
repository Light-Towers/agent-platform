# 架构优化借鉴方案（基于开源标杆调研）

> 状态：提案（待评审）
> 关联文档：`docs/competitive-landscape.md`（对标调研）、`docs/architecture-boundary-app-vs-agent-federation.md`
> 调研来源：LangChain(144k★)、Dify(152k★)、AutoGen(60k★)、CrewAI(57k★)、OpenAI Agents SDK(29k★)、DeepAgents(langchain-ai)
> 上游内核蓝本：[Light-Towers/reliable-agent](https://github.com/Light-Towers/reliable-agent)

## 0. 背景与目标

当前 `agent-platform` 已实现 LangChain/LangGraph 重度使用，并在 `agent_federation/` 视图直接站在 DeepAgent 库（`create_deep_agent`）之上。本轮调研确认：项目在**内核分层零耦合**（`agent-core`/`shared-schemas`）、**extras 隔离重依赖**（`sql`/`mcp`/`pdf`/`otel`）上已对齐开源最佳实践。

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

但存在 5 处与高 star 项目共识的差距，且 `app/` 与 `agent_federation/` 双轨编排并存。本方案**不推翻重写**，而是提出**分阶段、低风险、可独立测试**的优化，每项均保留现有内部契约兼容，避免全局回归。

## 1. 现状定位（当前架构快照）

| 维度 | 现状 | 文件锚点 |
|---|---|---|
| 状态定义 | `AgentState(BaseModel)`，**Pydantic 运行时校验**（优化 A 已落地） | `app/agent/state.py:21` |
| 输入护栏 | `guard_input()` 已下沉为 `agent_core.guardrails.input_guard` 共享内核，agent_federation/app 双视图统一入口 | `agent_core/guardrails/input_guard.py` |
| 长期记忆 | `MemoryBackend` 协议 + `PgVectorMemoryBackend`（默认）+ `CompositeMemoryBackend` 预留；门面 `longterm.py` | `app/memory/memory_backend.py` |
| 依赖管理 | `uv workspace` 成员声明已启用（根 `[tool.uv.workspace]` + 各子包去重 sources），monorepo 统一解析 | `pyproject.toml:65` |
| 工程门禁 | `Makefile`（make install/lint/test/eval/ci）+ 全仓 ruff 绿 + pytest 门禁可用 | `Makefile` |
| 编排 | `app/` 自研 Supervisor 图 vs `agent_federation/` `create_deep_agent`，双轨（优化 E 已落地，内核/契约层收敛，非合并代码） | `app/agent/graph.py:33` vs `agent_federation/agent/main_agent.py:118` |

## 2. 优化项清单（按优先级与风险分级）

### 优化 A：`AgentState` 升级为 Pydantic BaseModel（中优先级 / 低-中风险） ✅ 已落地

- **借鉴来源**：CrewAI Flows 用 `class MarketState(BaseModel)` 在 Flow 步骤间结构化传递状态；OpenAI Agents SDK 全链路 Pydantic 模型校验。
- **当前差距**：`TypedDict` 只在静态类型检查期生效，运行时节点写入脏字段/类型错误只能等下游崩溃。
- **方案要点**：
  1. 将 `app/agent/state.py` 的 `AgentState` 改为 `pydantic.BaseModel`，保留 `messages: Annotated[list, add_messages]` 的 reducer 语义（Pydantic 兼容 `Annotated`）。
  2. ✅ 已落地（2026-08-16）：`route` 字段枚举化为 `Literal["search","rag","sql","direct","mcp","blocked"]`（与 `graph.py` 条件分支键一一对应），节点写入非法路由值由 Pydantic 立即拦截；新增 `_validate_state()` 入口断言（校验 `question` 非空），在 `route_node` 入口调用，脏 state 在节点边界即时暴露。
  3. 保留 `total=False` 等价性：用 `Field(default=None)` 表达可选字段。
- **兼容性**：LangGraph `StateGraph` 同时支持 TypedDict 与 Pydantic model 作为 state schema，无需改动 `graph.py` 的节点签名。
- **测试边界**：仅需回归 `app/agent/graph.py` 全流程 + `tests/` 中 state 相关用例（约 40 用例中的 state 读写部分）。
- **收益**：节点边界脏 state 即时暴露，减少"脏数据穿透到 synthesize"类偶发 bug。

### 优化 B：输入护栏下沉为共享内核 + 双视图统一入口（中优先级 / 中风险） ✅ 已落地

- **借鉴来源**：OpenAI Agents SDK 将 Guardrails 作为 Agent 一等公民；DeepAgents 用 `RubricMiddleware`/`TodoListMiddleware` 栈式横切。
- **当前差距**：`guard_input()` 是外层包裹，与编排解耦但无法作为反思/规划链的一环，且 `app/` 视图完全无护栏。
- **方案要点**：
  1. **保留** `agent_federation/gateway/input_guard.py` 的全部检测逻辑（`detect_pii`/`redact_pii`/`detect_injection`/`guard_input`），不重写规则。
  2. ✅ 已落地（2026-08-16）：新增 `agent_federation/gateway/guard_middleware.py`，将内核 `guard_input` 包装为 DeepAgent `AgentMiddleware`（`GuardMiddleware`），在 `before_agent` 钩子对入口 user 文本做脱敏改写 + injection 拦截；`main_agent._build_middleware()` 按 `GUARD_ENABLED` 开关注入（`GuardMiddleware()`），带失败降级，与 TodoList / Rubric 共用 `create_deep_agent(middleware=[...])` 统一挂载点。至此 `guard_input` 不再是 `app` 侧专属手动调用，agent_federation 视图 agent 也默认经过输入护栏。
  3. `app/` 视图在 `route_node` 前插入同一 `guard_input` 调用（单函数复用，非重写）。
- **兼容性**：检测函数签名与返回字典不变；仅新增包装，旧调用方（`agent_federation` 网关入口）行为不变。
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

- **借鉴来源**：本项目 `agent_federation/` 已验证 `create_deep_agent` 可用；CrewAI 双范式（Crews+Flows）说明"自主 vs 可控"可共存但需统一底座。
- **当前差距**：`app/` 自研 Supervisor 图与 `agent_federation/` 应用层重复实现编排，技术栈分裂，维护双倍成本。**但调研确认双轨零代码耦合，且已通过 `agent_core` 共享内核**；重复主要在"应用层编排形态"而非"能力实现"。
- **收敛范围（基于调研修正方向）**：**不在编排层合并代码**——强行以 `create_deep_agent` 为底座重写 `app/graph.py` 会破坏 `app` 的 admission/coordinator/revert/PG checkpoint/sqlglot 双保险/SSE 外壳，且丢失 `agent_federation` 的联邦远程治理。正确收敛在**共享内核层与联邦契约层**：
  1. `shared_schemas` 契约对齐：`agent_federation/agent/async_subagents.py` 的远程响应接入 `QueryResponse` 断言（消除不对称）。
  2. SQL 守卫统一评估：`agent_federation/tools/sql_validation.py`（sqlparse）与 `agent_core.sql.guard`（sqlglot）的方言兼容评估（可选）。
  3. `MemoryBackend` 协议下沉 `agent_core.memory`，供双轨复用（可选）。
- **必须保留**的自研外壳（硬约束，禁止为"统一"而弱化）：`app/main.py` 的 admission 排队、session coordinator、SSE 事件映射、语义缓存、`sqlglot` SQL 守卫、PG checkpoint、`gateway/input_guard.py` 合规护栏；`agent_federation` 的联邦 remote subagent 委派治理（重试/429/健康检查）。
- **风险**：编排核心若误合并影响面最大；故收敛限定在内核/契约层，每阶段独立可测。
- **专项规划**：详见 `docs/plan-e-dual-track-convergence.md`（P4.1~P4.3 已实施，经独立审核修订后落地）。

### 优化 F：自研外壳基础设施化（中优先级 / 可选，独立专项）

- **来源**：用户决策——若把 `app` 的 5 段自研外壳补到 `agent_federation`，需回答"app 的 LangGraph 逻辑是否还有意义"。澄清：外壳是**团队自研逻辑、非 LangGraph 独有**；补外壳=搬家不是换框架；补完后双轨差异收敛为纯编排风格差异（确定性 DAG vs 涌现委派）。
- **结论**：`app` 显式 `StateGraph` 编排可退役（被 DeepAgents 风格吸收），但 LangGraph 内核永远在（DeepAgents 依赖之），外壳代码搬家不消失。
- **收敛方式（不做全量迁移）**：把 admission/coordinator/revert/SQL 双保险/SSE 抽为**独立可复用横向基础设施**，双轨共用同一套、编排层各自保留；继承 §3 护栏（编排不可合并）。
- **前置**：先修 `agent_federation/api/server.py:165` API_KEY 模式 thread_id 每次重建导致会话断裂的 bug（否则接 PG checkpoint 也救不了多轮对话）。
- **专项规划**：详见 `docs/plan-e-dual-track-convergence.md` 末尾「F 外壳基础设施化」节（P4.4，可选）。

### 优化 G：引入 `workspace_id` 工作空间隔离（高优先级 / 低-中风险） ✅ 已落地（feat/workspace-isolation）

- **来源**：跨会话记忆架构讨论（对标 codex 的 workspace 锚）。澄清：**RAG 知识库 ≠ 跨会话记忆**，二者此前无统一归属维度、长期记忆仅按 `user_id` 隔离（app 默认 `default` 桶串味）。引入 `workspace_id` 作为统一归属/隔离主键，同时串起 RAG 文档与长期记忆，但语义分离。
- **决策（A 模式）**：`workspace_id` 由**客户端显式传**（请求字段，默认 `default`），**仅 app 内部隔离**，不写 `shared_schemas`（联邦网关无感）。不做 resume/fork（用户决策：暂不需要）。
- **三者关系**：RAG 知识库 = 工作空间的「静态硬盘」（用户上传文档）；长期记忆 = 工作空间的「动态经验」（跨会话沉淀 Q/A）；`workspace_id` = 绑定二者的「文件夹」。RAG 本身不跨会话（每次会话重检索），跨会话能力由 `memories` 表 + checkpointer 提供并受 workspace 隔离。
- **落地改动**：
  - `app/infra/db.py`：`chunks` 表加 `workspace_id TEXT NOT NULL DEFAULT 'default'` 列 + 索引；`ensure_schema` 对存量库幂等 `ALTER TABLE ... ADD COLUMN`（捕获 duplicate_column）。
  - `app/rag/store.py`：`add_document`/`retrieve_chunks`/`_vector_ids`/`_bm25_ids` 全链路按 `workspace_id` 过滤（向量路用 `vector_search(where=...)`，BM25 语料加载与缓存签名含 `workspace_id`）。
  - `app/schemas.py`：`QueryRequest` 加 `workspace_id`（默认 `default`）；`app/api/routes.py` 的 `/import` 接口加 `workspace_id` 表单参并写入。
  - `app/agent/state.py`：`AgentState` 加 `workspace_id`；`routes.py` 注入初始 state；`graph.py` 的 `route_node/rag_node/synthesize_node` 按 `workspace_id` 调 `recall/remember` 与 `rag_query`。
  - `app/memory/longterm.py`：门面 `recall/remember` 改为以 `workspace_id` 作为内核隔离过滤键（复用内核 `recall(pool, user_id, ...)` 的 `user_id` 形参位），**内核 `PgVectorMemoryBackend` 零改动**（表结构/其余维度不变）。
- **护栏**：保持内核零依赖铁律，未触碰 `agent-core` 后端契约；`workspace_id` 隔离在 app 业务层完成，符合 §3 护栏第 1 条。
- **后续可扩展（本分支未做）**：B 模式（按 `user_id` 推导默认 workspace）、`shared_schemas` 联邦化（agent_federation 网关感知 workspace）、resume/fork 指定历史 session。

### 优化 H：长期记忆质量升级——三层抽取 + 三分存储 + consolidation/forgetting（中优先级 / 中风险）

> 状态：✅ 已落地（2026-08-19 审查核销，ADR-0004 v2.1 阶段 1~3 已下沉内核：`app/memory/longterm.py` 抽取(D1)/三层存储(D2)/分层加权召回(D3)/巩固+遗忘(D4/D5) + 内核 `agent_core.memory.typed`（`recall_typed`/`remember_typed`/`consolidate`/`forget`/`MemoryType`）；`SEMANTIC_MEMORY_TYPED` 总开关控制退化路径）
> 前置：依赖优化 G 的 `workspace_id` 隔离（记忆归属维度已就位）

#### H.0 问题定义（为什么说当前长期记忆"质量低"）

当前 `app/memory/longterm.py` 的 `remember()` 把**整条 `"Q: ...\nA: ..."` 原文**直接灌进 pgvector，recall 只做**单一语义向量召回**。这带来三类问题：

1. **噪声与 PII 风险**：原始对话包含寒暄、冗余、用户隐私字段，全量入库既稀释检索精度又违规留存 PII 原文。
2. **检索无结构**：recall 只能「语义相似度」一条路，无法区分"这是发生过的事（episodic）""这是用户偏好（semantic）""这是该怎么做事（procedural）"，导致回答时误用记忆类型。
3. **无巩固与遗忘**：记忆只增不减，`memories` 表无限膨胀，旧事实与后来修正的事实并存，且同样权重参与召回——经典「记忆腐化」。

对标 OpenAI Agents SDK（`Memory` 抽象 + `memory_search` 工具）、LangGraph `long-term-memory`（LLM 抽取结构化事实再存）、Mem0（episodic/semantic/procedural 三层 + consolidation），本优化落地**同质但保持内核零依赖**的方案。

#### H.1 设计决策（five design decisions，复用跨会话记忆讨论结论）

| # | 决策 | 落地方式 |
|---|---|---|
| D1 | **抽取不存原文** | `remember` 先经 LLM 抽取为结构化事实（`surface_form` 摘要 + 元数据），原文不入记忆库；PII 在抽取阶段即被剥离 |
| D2 | **结构化 + 元数据** | `memories` 表扩展 `memory_type`/`importance`/`created_at` 三列；事实按类型分层 |
| D3 | **分层混合检索** | recall 按 `memory_type` 加权 + 语义召回 + importance 衰减排序 |
| D4 | **consolidation 巩固** | 新事实入库时比对存量：冲突则按时间/importance 更新而非重复插入；相似则合并 |
| D5 | **forgetting 遗忘** | 按 `importance × 衰减(created_at)` 打分，低于阈值的低价值记忆在 consolidation 窗口内惰性淘汰 |

#### H.2 三种记忆类型（three-type 模型）

| 类型 | 含义 | 抽取信号 | 召回偏好 |
|---|---|---|---|
| `episodic` | 特定发生过的事（"用户上周报过账"） | 含时间/事件/结果 | 高 importance，短期强权重 |
| `semantic` | 用户偏好/事实/人设（"用户是财务，讨厌冗长"） | 稳定陈述、偏好表达 | 长期稳定，跨会话复用 |
| `procedural` | 该怎么做事（"这类报表用 X 模板"） | 指令性、方法论 | 高 importance，覆盖式更新 |

#### H.3 存储结构（三分存储 + 共享检索，遵守 §3 护栏第 1 条）

**关键护栏**：`agent-core` 的 `MemoryBackend` 契约（`recall/remember`）与 `PgVectorMemoryBackend` 实现**不得修改**（零依赖铁律）。因此 H 在 **app 层**落地：

- **复用内核表**：沿用内核 `PgVectorMemoryBackend` 的 `memories` 表（列：`user_id`/`content`/`embedding`），**app 侧幂等 `ALTER TABLE` 扩展** `memory_type TEXT`/`importance FLOAT`/`created_at TIMESTAMPTZ`（app 是该表唯一写方，安全；不改内核 DDL 文件，避免破坏非 app 消费方）。
- **三分检索入口**：app 门面 `recall` 内部按 `memory_type` 分别加权召回后融合（单一混合结果返回，对 graph 透明）。
- **共享检索**：对外仍暴露 `recall(pool, workspace_id, question, k)`，graph 无感知类型分层。

> 注：真正的「图存储（Graph）/用户画像（Profile）/情景向量（Episodic vector）」三库分离是 Mem0 式重架构，超出本优化范围。H 用**单表 + 类型列**近似三分语义，零新增依赖、可独立测试，符合「分阶段低风险」原则。未来若需真图存储，列为优化 H2。

#### H.4 落地改动清单

- `app/infra/db.py`：`ensure_schema` 幂等 `ALTER TABLE memories ADD COLUMN memory_type/importance/created_at`（捕获 duplicate_column）。
- `app/memory/memory_backend.py`：app 侧 `PgVectorMemoryBackend` 的 `remember/recall` 支持写/读 `memory_type`/`importance`/`created_at`；新增 `remember_fact(pool, workspace_id, fact, memory_type, importance)` 与 `recall_typed(pool, workspace_id, question, k)`。
- `app/memory/longterm.py`：门面升级
  - `remember(pool, workspace_id, q, a)`：LLM 抽取结构化事实 → `remember_fact`（带类型/重要性）；抽取失败/未开启时退化存原文（保持现有行为）。
  - `recall(pool, workspace_id, question, k)`：调 `recall_typed` 分层加权融合。
  - 新增 `consolidate(pool, workspace_id)`（冲突更新+相似合并+低价值淘汰）与 `forget(pool, workspace_id, memory_id)`。
- `app/config.py`：新增开关 `memory_extraction_enabled: bool = False`（默认关，无 LLM 时退化）、`memory_forget_threshold: float = 0.1`。
- `app/agent/graph.py`：`synthesize_node` 完成后调 `remember`（抽取路径）；`route_node` 前调 `recall`（分层路径）。

#### H.5 风险与门禁

- **LLM 抽取不可控**：默认 `memory_extraction_enabled=False`，退化路径与当前行为完全一致；抽取路径单测用 mock LLM 验证，不依赖真实 API。
- **ALTER TABLE 兼容性**：幂等捕获 `duplicate_column`，存量库安全升级。
- **回归总闸**：`pytest tests/ -q` + `python -m eval.run_eval` 全绿；新增 `tests/test_longterm_h.py` 覆盖抽取/退化/consolidate/forget。

#### H.6 后续（未纳入本优化）

- H2：真三分存储（Graph + Profile + Episodic vector）独立表/库。
- 精确回忆机制：按 `thread_id` + checkpointer 回溯历史对话原文（与语义回忆正交，见跨会话记忆讨论，已由优化 I 落地）。

### 优化 I：精确回忆机制——thread_id + checkpointer 回溯历史原文（中优先级 / 低风险）

> 状态：已落地（feat/workspace-isolation 分支，独立于 H）
> 前置：内核 `get_checkpointer` 工厂已产出 `AsyncPostgresSaver`，挂于 `app.state.checkpointer`；
>       `/query` 已用 `thread_id` 驱动会话状态（优化 G 的 `resolve_thread_id`）。

#### I.0 为什么需要精确回忆（与 H 正交）

跨会话记忆有两路，互为补充：

| 维度 | 优化 H（语义回忆） | 优化 I（精确回忆） |
|---|---|---|
| 目标 | 跨会话「大概记得」用户偏好/事实 | 精确定位「某次聊天具体说了什么」 |
| 载体 | LLM 抽取结构化事实 + pgvector | LangGraph checkpointer 原始消息 |
| 匹配 | 语义相似度 | 字面原文 / `thread_id` 定位 |
| 丢失风险 | 抽取可能丢原文细节、PII 剥离 | 无（存原文） |
| 隔离维度 | `workspace_id`（memories 表） | `thread_id`（checkpointer 表，会话级） |

用户原问"能不能精确的找到之前聊天内容"——H 答不了（它只存提炼事实），只有 I 能答。两路并存才是完整跨会话记忆。

#### I.1 设计决策

- **复用内核 checkpointer**：`AsyncPostgresSaver.alist_messages({"configurable": {"thread_id": ...}})` 原生支持按会话取回全部消息，零新增存储、零内核改动。
- **精确匹配语义**：`keyword` 过滤走字面子串匹配（非向量语义），保证「找到原话」的确定性。
- **鉴权一致**：`/history` 复用 `verify_api_key` + `resolve_thread_id`，与 `/query` 同源归属（thread_id 由 session_id + api_key 推导，他人不可越权读）。
- **降级安全**：无 checkpointer（内存/未初始化）时返回 503，不泄漏空数据误判。

#### I.2 落地改动清单

- `app/memory/recall_exact.py`（新）：`get_thread_history(checkpointer, thread_id, keyword, limit)` 规整 `BaseMessage` → `{index, role, content, id, created_at}`；`search_in_thread` 关键词精确检索。role 归一化（human→user, ai→assistant）。
- `app/schemas.py`：新增 `HistoryItem` / `HistoryResponse`。
- `app/api/routes.py`：新增 `GET /history?session_id=&keyword=&limit=`，依赖 `verify_api_key`，从 `app.state.checkpointer` 取数据。
- 单测 `tests/test_recall_exact.py`：mock checkpointer 的 `alist_messages`，验证规整/关键词过滤/limit/角色归一化。

#### I.3 风险与门禁

- **checkpointer 依赖**：接口依赖 `app.state.checkpointer`；内存模式（无 PG）时 `get_checkpointer` 降级 `InMemorySaver`，仍能按 thread_id 回溯（测试用 mock）。
- **PII 暴露面**：`/history` 返回原文，鉴权与 `/query` 同强度（api_key + 推导 thread_id），无越权面；如需更严可加 `workspace_id` 绑定校验（留作后续）。
- **回归总闸**：`pytest tests/ -q` 全绿；新增 `tests/test_recall_exact.py` 覆盖规整/关键词/limit/归一化，不连 PG。

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
| TB-1 | **DF 双 LLM 协议冗余**：`dialogue_framework.shared.llm.base_client.BaseChatClient` 与 `agent_core.llm.providers.BaseLLMProvider` 签名不兼容、互不对接 | `architecture-boundary-agent-core-vs-dialogue-framework.md:63` | 已闭环 | ✅ 已落地（2026-08-16，桥接形式）：`dialogue_framework/shared/llm/core_adapter.py` 新增 `LLMCoreClient` 桥接内核 `BaseLLMProvider`；DF 弃用自有 `BaseChatClient`、对齐内核协议；**不合并/删除 dialogue-framework**（详见 §6.3） |
| TB-2 | **DF 双 memory 抽象冗余**：`dialogue_framework.core.Tracker`（slots/events/stack）未使用 `agent_core.memory.ConversationMemory` | 同上:64 | 已闭环 | ✅ 已落地（2026-08-16，桥接形式）：`dialogue_framework/core/tracker_memory.py` 新增 `TrackerConversationMemory` 适配内核 `ConversationMemory`，`Tracker.to_conversation_memory()` 挂载；不合并两包（详见 §6.3） |
| TB-3 | **uv workspace 环境脆弱**：根 `uv sync` 会卸载非根 member 包（实测卸载 24 包，含 agent_federation-app），默认环境不含非根包依赖 | 实施过程实测 | 中（已缓解） | **已修复**：根因是 uv workspace 默认 `uv sync` 只装根包。固化约定为 `uv sync --all-packages --extra dev`（装全部 workspace 包 + dev 工具），单包测试用 `uv run --package <pkg> ...`；运行约定已写入 `README.md` uv workspace 段。裸 `uv sync` 仍会卸载非根包，勿直接使用 |
| TB-4 | **M5 语义缓存统一未落地**：`agent_core.cache` 已建 `CacheStats`/`build_cache_key` 单一真相，但 app(`PgSemanticCache`)/agent_federation(`ValkeySemanticCache`) 尚未统一到 `BaseSemanticCache` 接口 | `m5-semantic-cache-plan.md`（纯草案，未实施） | 中 | ✅ 已落地（2026-08-16）：`agent_core.cache` 新增 `BaseSemanticCache` Protocol + 零依赖 `build_cache_key` 纯函数（单一真相）；agent_federation `layers.py` 复用内核 `build_cache_key`（移除本地 hash 重复，I 规则清理 hashlib/json）；app `infra/cache.py` docstring 标注遵循协议、不跨后端共享数据。补 `agent-core/tests/test_cache_key.py`。遵循 §6 约束：仅统一接口与 key 构造，不跨后端共享缓存数据 |
| TB-5 | **agent_federation 联邦契约统一（原 TODO）**：`shared_schemas` 在 agent_federation 侧原未直接复用（仅 app 侧用），已在优化 E/P4.1 补齐断言——**已闭环**，此处仅作历史登记 | `architecture-boundary-app-vs-agent-federation.md:69` | 已解决 | — |
| TB-9 | **双轨职责重叠（意图/改写双份）**：`app.decide_route` 与 `agent_federation/agent/intent/*` + `rewrite/` 各自实现意图分类与 Query 改写，策略可能分歧、双份维护 | `dual-track-architecture-analysis.md` AR-1 | 高（仅 SQL/契约已收口，路由/改写仍双份） | 以 `app.decide_route` + `agent_core` 为路由真相源；agent_federation 侧复用或经内核桥接，禁止编排层合并（护栏 §3） （2026-08-19 审查核销：意图分类已收口到内核 `agent_core.intent.classify_intent`（`agent_federation/agent/main_agent.py` 直用），`app/agent/intent_bridge.py` 为双轨标签映射单一真源；`rewrite/` 为联邦 Phase 2 subquery 分解专用，app 侧无对应实现，无双份） |
| TB-10 | **双轨记忆语义不等价**：`app` 有 pgvector 长期记忆 + PG checkpoint + revert；`agent_federation` 仅 `InMemorySaver`，无长期记忆（E-3 已下沉 `MemoryBackend` 协议但未挂后端） | `dual-track-architecture-analysis.md` AR-2 | 高（跨轨无法共享长期上下文） | `create_deep_agent` memory 挂载点接入内核 `MemoryBackend`；短期文档固化"agent_federation 无长期记忆"边界 （2026-08-19 审查核销：`agent_federation/agent/memory/main_agent_memory.py` 已挂 typed 长期记忆（`recall_typed_context`/`remember_episodic`，thread_id→workspace_id 透传），checkpointer 走内核 `get_checkpointer`（Mongo 持久化 / InMemory 降级）；「无长期记忆」边界已解除） |
| TB-11 | **双轨配置体系分裂**：`app` 用 pydantic-settings `Settings`；`agent_federation` 用 dataclass+dotenv+YAML，能力开关散落 env | `dual-track-architecture-analysis.md` AR-3 | 中 | 长期 agent_federation 配置收敛到 pydantic-settings 或复用 `app.Settings`；短期 README 枚举全部 env 开关与默认值 （2026-08-19 第一步已落地：README 环境变量表 + `.env.example` 以源码为真相源全量盘点 80+ 开关（含共享内核 `agent_core.memory.*` 11 项），修正 `SUBAGENT_RETRY_BASE` 默认值偏差 1.0→0.5、移除源码中已不存在的过时 `MYSQL_POOL_RESET_SESSION`；长期 pydantic-settings 收敛保留，待出现真实配置复用需求） |
| TB-12 | **共享内核采用度不对称（残余）**：`agent_federation` 引 `agent_core` 24 处 / `app` 7 处；缓存 key 已统一（TB-4）但 `PgSemanticCache`/`ValkeySemanticCache` 未统一到 `BaseSemanticCache` 实现层 | `dual-track-architecture-analysis.md` AR-4 | 中（部分已闭环：E-1/TB-4/TB-5） | 新增内核能力强制双轨同步接入；缓存后端实现层对齐 `BaseSemanticCache` （2026-08-19 审查核销：`PgSemanticCache` / 联邦 `SemanticCache` 均已实现 `BaseSemanticCache` 统计接口（`get_stats`/`reset_stats`），key 构造统一内核 `build_cache_key`，实现层对齐闭环） |
| TB-13 | **双轨认知/维护成本**：9 包 monorepo + 两套编排哲学（StateGraph 边思维 vs DeepAgents 委派思维）+ SSE/WS 双网关，排障需先判轨 | `dual-track-architecture-analysis.md` AR-5 | 中（结构性） | 优化 F：抽自研外壳为共享基础设施，双轨共用；`AGENTS.md` 固化「新业务默认走哪条轨」决策树 |
| TB-14 | **agent_federation 外壳缺失 + thread_id 会话断裂**：`agent_federation/api/server.py:165` API_KEY 模式每次请求生成新 `thread_id`，使 checkpointer 形同虚设（即便换 PG 也救不了多轮）；且缺 admission/coordinator/revert/SSE 外壳 | `plan-e-dual-track-convergence.md` §F | 高（阻断 B 侧持久化与回退） | ~~优化 F P4.4：先修 thread_id 复用~~ ✅ **已落地（2026-08-18 审查核销）**：`agent_federation/api/auth.py` 的 `resolve_thread_id` 已按密钥派生稳定 `thread_id`，多轮会话断裂已修复（审查实码确认）；余「抽外壳为共享基础设施」仍为 P4.4 独立项，按文档执行时勿在 thread_id 上重复投入 |

### 6.2 范围外 / 未核验项（需独立子任务）

| 编号 | 问题 | 来源 | 说明 |
|---|---|---|---|
| TB-6 | **kefu 返回符合性逐项核验**：优化 E 仅对 `async_subagents` 加 `QueryResponse` 断言（消费侧），未反向核验 kefu `/invoke` 是否逐字段符合 `QueryResponse`（含 `fallback`/`error`/`sources` 字段形态） | `plan-e-dual-track-convergence.md:95` S-5③ | ✅ 已落地（2026-08-16）：逐项核验 kefu `/invoke` 返回的 `QueryResponse` 字段（answer/data.content.intent/source/trace_id/latency_ms/intent/fallback）均与 `shared_schemas.query.QueryResponse` 契约一致；发现并修复"形状合法但内容空洞"盲区——kefu 图未产出 response 时返回空 answer（契约通过但语义退化）。收口：① kefu `_run_kefu` 显式 `fallback=False` + 空 answer 日志告警；② 消费侧 `_HttpSubAgent` 抽出 `_normalize_response` 纯函数，新增 `E1_CONTENT_ASSERT` 内容断言（answer 非空，与形状断言分离可独立回滚）；③ 新增 `agent_federation/tests/unit/test_async_subagents_contract.py` 中 3 例 TB-6 双向符合性测试（kefu 真实字段提取 / 空 answer 告警 / 开关 off）。字段形态结论：kefu 未传 `error`/`sources`（契约非必填，合法）；`fallback` 此前隐式默认，现显式 |
| TB-7 | **docker compose 端到端冒烟**：`docker-compose.yml` 已存在，但缺一键端到端冒烟验证 | `research-proposal.md:120` | 可选；需服务可达环境 |
| TB-8 | **eval 门禁 CI 化（分层）**：本地 `python -m eval.run_eval` 12/12 通过，但 LLM 质量评测依赖 LLM/服务可达，CI 不可达时仅本地人工验证 | `architecture-improvement-plan.md:134` | ✅ 已落地（2026-08-16 起，分层收敛于 2026-08-16）：**第 1 层确定性门禁** `agent-platform-ci.yml` 改用 `make ci`（lint+pytest+启发式 eval，无 LLM 依赖永远可达），install 统一 `make install` 覆盖全部 workspace 包，消除手写命令与本地双路径漂移；**第 2 层 LLM 质量雷达** `eval-llm.yml`（定时 cron + `workflow_dispatch` 手动，非阻塞 `continue-on-error`）跑 `make eval-llm-required`（`--require-llm` 真评测，不可达显式 SKIP 退出码 2 不假装通过），结果存 artifact 供趋势查看，不卡 push。`run_eval.py` 文档头已对齐分层语义。CI 不再硬设 LLM 阈值，消除 `--fail-below 1.0`/`0.8` 与不可达性的根本矛盾 |
| U-1 | **QueryRequest 入站双写兼容**：`app/schemas.py` 给 `query`/`session_id` 加 `AliasChoices` 接收旧名 `question`/`thread_id`，属隐性兼容债 | `shared_schemas.query.QueryRequest` + `app/schemas.py:41-55` | 已闭环 | **已移除（2026-08-16）**：普查存量客户端后确认无生产调用方仍发旧名（agent_federation `run-all.py` 调 adapter `/query` 已用标准名 `query`；仅两个测试用旧名），移除 `AliasChoices` 双写兼容，入站契约收敛为纯标准名 `query`/`session_id`；同步更新 `tests/test_api_smoke.py`、`agent-core/tests/test_guardrails.py` 示例字段名，并清理未使用的 `AliasChoices` import。内部 `AgentState.question` 为 graph state 字段，与入站契约无关，保持不动（强行统一内部命名为 `query` 属纯 churn，收益为零） |

### 6.3 说明

- TB-1/TB-2 是本次 v2"双轨收敛"的**延伸项**，按边界文档判定为低优先级后续技术债。v2 中已以**桥接适配**形式落地（非合并/删除 dialogue-framework，符合红线字面）：`dialogue_framework/shared/llm/core_adapter.py`（`LLMCoreClient` 桥接内核 `BaseLLMProvider`）+ `dialogue_framework/core/tracker_memory.py`（`TrackerConversationMemory` 适配内核 `ConversationMemory`），并补 `tests/test_tb_bridge.py`。DF 仍为独立包、未合并，满足护栏清单红线；详见 §6.1 TB-1/TB-2 行"✅ 已落地"标注与 CHANGELOG。
- TB-3 是**工程环境问题**，与代码正确性无关，但会误伤开发者环境，建议尽早固化运行约定。
- TB-4 是已规划未实施的**独立专项**（M5），与 E 平行，可单独排期。

*生成依据：v2 实施过程实测 + `docs/` 下各边界调研与专项规划文档登记的待办项汇总（2026-08-16，TB-1/TB-2 以桥接形式落地后修订）。*

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
| #7 | `requirements.txt` 未同步 `shared-schemas`/`sqlglot` | 根目录无 requirements.txt（uv workspace 管理）；`agent_federation/requirements.txt` 漏列 `shared-schemas`/`sqlglot` | ✅ 已修：`agent_federation/requirements.txt` 补 `-e ../shared-schemas` + `sqlglot>=25.0` |
| #8 | SQL 守卫 `LIMIT>100` 截断 + 文本重生成 | `agent_core.sql.guard` 的 `max_rows`（默认 100，`SQL_GUARD_MAX_ROWS` 可配）是**有意的防护上限**，防 `SELECT *` 拖垮 DB；截断后返回规整 SQL 是正常归一化 | 维持现状：安全设计，非缺陷 |
| #10 | 仅 workspace 安装 + 缺 CHANGELOG | 工程约定问题 | ✅ 已修：新增 `CHANGELOG.md`，明确 uv workspace 为唯一安装入口 |
| #11 | `_validate_state`/`guard_middleware` 文档提及但代码不存在 | 实为 §2 优化 A/B 要点2 规划项未实施；标题"✅已落地"误导 | ✅ 已勘误：优化 A 要点2（`route` 枚举化 + `_validate_state`）与优化 B 要点2（`guard_middleware`）均已于 2026-08-16 落地（§2 两者标题均回升"✅已落地"）；原"提及但代码不存在"已消解 |
| #12 | `make type` 是 ruff 别名 | 非缺陷 | 无需修 |
| #13 | `rag_query` 端点 httpx 兜底 | 实际优先走 `AsyncSubAgent`，httpx 仅兜底且已收敛，影响窄于报告 | 维持现状 |
| #14 | `zhanggui-zhiku` 双 `uv.lock` | 子包独立 lock 与 workspace 根锁冲突 | ✅ 已修：删除 `zhanggui-zhiku/uv.lock`，统一根锁（`uv lock` 验证通过） |
| #15 | logger name 变更 | 核验：app 全量 `getLogger(__name__)` + 顶层 `agent_core` 命名已规范 | 无需修：非缺陷 |

*门禁：本轮修复后 `ruff check .` 全绿；CI 门禁经 `make test` 分三个独立 pytest session 串联——根（`tests` + `agent-core/tests`）、`agent_federation/tests/unit`（排除预存冲突的 `test_tool_registry.py`）、`kefu-service/tests`，三套件全部通过即为门禁达标（具体例数随用例增长，不在此固化，避免文档数字漂移）。CI 盲区修复详见严重 #2。*

