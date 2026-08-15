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
| 依赖管理 | `uv.lock` 存在，子包用 `[tool.uv.sources]` editable（uv workspace 成员声明暂缓，见 §4） | `pyproject.toml:65` |
| 工程门禁 | `Makefile`（make install/lint/test/eval/ci）+ 全仓 ruff 绿 + pytest 门禁可用 | `Makefile` |
| 编排 | `app/` 自研 Supervisor 图 vs `deepagents/` `create_deep_agent`，双轨（优化 E 独立专项，本轮不实施） | `app/agent/graph.py:33` vs `deepagents/agent/main_agent.py:118` |

## 2. 优化项清单（按优先级与风险分级）

### 优化 A：`AgentState` 升级为 Pydantic BaseModel（中优先级 / 低-中风险） ✅ 已落地

- **借鉴来源**：CrewAI Flows 用 `class MarketState(BaseModel)` 在 Flow 步骤间结构化传递状态；OpenAI Agents SDK 全链路 Pydantic 模型校验。
- **当前差距**：`TypedDict` 只在静态类型检查期生效，运行时节点写入脏字段/类型错误只能等下游崩溃。
- **方案要点**：
  1. 将 `app/agent/state.py` 的 `AgentState` 改为 `pydantic.BaseModel`，保留 `messages: Annotated[list, add_messages]` 的 reducer 语义（Pydantic 兼容 `Annotated`）。
  2. 新增节点入口处的 `_validate_state()` 校验函数，对 `route` 枚举、必填字段做断言。
  3. 保留 `total=False` 等价性：用 `Field(default=None)` 表达可选字段。
- **兼容性**：LangGraph `StateGraph` 同时支持 TypedDict 与 Pydantic model 作为 state schema，无需改动 `graph.py` 的节点签名。
- **测试边界**：仅需回归 `app/agent/graph.py` 全流程 + `tests/` 中 state 相关用例（约 40 用例中的 state 读写部分）。
- **收益**：节点边界脏 state 即时暴露，减少"脏数据穿透到 synthesize"类偶发 bug。

### 优化 B：输入护栏下沉为共享内核 + 双视图统一入口（中优先级 / 中风险） ✅ 已落地

- **借鉴来源**：OpenAI Agents SDK 将 Guardrails 作为 Agent 一等公民；DeepAgents 用 `RubricMiddleware`/`TodoListMiddleware` 栈式横切。
- **当前差距**：`guard_input()` 是外层包裹，与编排解耦但无法作为反思/规划链的一环，且 `app/` 视图完全无护栏。
- **方案要点**：
  1. **保留** `deepagents/gateway/input_guard.py` 的全部检测逻辑（`detect_pii`/`redact_pii`/`detect_injection`/`guard_input`），不重写规则。
  2. 新增薄适配层 `deepagents/gateway/guard_middleware.py`：将 `guard_input` 包装为 DeepAgent Middleware（`@middleware`/`BaseMiddleware`），挂到 `create_deep_agent(middleware=[..., GuardMiddleware])`（`main_agent.py:63`）。
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

### 优化 E：双轨编排收敛（高优先级 / 高风险，建议后置）

- **借鉴来源**：本项目 `deepagents/` 已验证 `create_deep_agent` 可用；CrewAI 双范式（Crews+Flows）说明"自主 vs 可控"可共存但需统一底座。
- **当前差距**：`app/` 自研 Supervisor 图与 `deepagents/` 应用层重复实现编排，技术栈分裂，维护双倍成本。
- **方案要点（仅方向，非本轮落地）**：
  1. 以 `create_deep_agent` 为统一底座，将 `app/graph.py` 的 `route/search/rag/sql/mcp` 节点改造为 subagent 或工具。
  2. **必须保留**的自研外壳：`app/main.py` 的 admission 排队、session coordinator、SSE 事件映射 `_node_event`、语义缓存（`cache/`）、`sqlglot` SQL 守卫、`gateway/input_guard.py` 合规护栏、联邦 remote subagent 委派治理（重试/429/健康检查）。
- **风险**：影响面最大（编排核心），需独立专项，且开启 `REFLEXION_ENABLED`/`PLANNER_ENABLED` 默认开关前需充分 eval。
- **收益**：消除双轨，免费获得并行委派/反思；但**本轮不实施**，待 A~D 落地且 eval 门禁稳定后再评估。

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
| P0 | 优化 D（Makefile + uv workspace） | 无业务代码改动 | `make install/test` 通过 | Makefile 已落地；uv workspace 成员声明暂缓（path-sources 已可用，见下） |
| P1 | 优化 A（`AgentState` → Pydantic） | `app/agent/graph.py` + state 用例 | pytest + eval 全绿 | ✅ 已落地（commit f0a5f43） |
| P2 | 优化 B（护栏共享内核 + 双视图统一入口） | 入口链路 + input_guard 单测 | pytest + eval 全绿 | ✅ 已落地（commit a23755e） |
| P3 | 优化 C（memory backend 协议） | `app/memory/longterm.py` 行为 | 新增 backend 单测 + eval 全绿 | ✅ 已落地（commit dd51aa9） |
| P4（后置） | 优化 E（双轨收敛） | 全量 | 独立专项 + eval 充分验证 | 独立专项，本轮不实施 |

> P0~P3 均为**局部改动 + 向后兼容**，每阶段结束跑 `make test`（含 40 单测）与 `make eval`（12 golden）即可确认无回归。P4 为架构级，单独立项。

**关于优化 D 的 uv workspace 成员声明（暂缓说明）**：当前各子包已通过 `[tool.uv.sources]` 的 `path` editable 引用 sibling 包，`uv.lock` 同步正常，Makefile 门禁（`make install/lint/test`）已可用，工程收益（统一入口 + 门禁）已达成。改为 `uv workspace` 成员声明会触及全部 7 个子包 + 根 + `uv.lock`，且 `zhanggui-zhiku` 使用 setuptools 而非 hatchling（与其余包不一致），workspace 下可能触发全量重 build，存在文档预警的"破坏现有 editable 安装"风险。按"先在隔离环境验证 `uv sync` 成功再提交"的缓解要求，该项不在本地直接推进，待有隔离验证环境时单独立项。

## 5. 风险与缓解

- **Pydantic state 与 LangGraph reducer 冲突**：`add_messages` 是 reducer 函数，Pydantic field 需验证其可承载；先在小图验证再全量。
- **middleware 包装改变调用时序**：`guard_input` 返回值字典结构保持不变，仅挂载位置变化；用现有网关单测覆盖。
- **uv workspace 破坏现有 editable 安装**：先在隔离环境验证 `uv sync` 成功再提交。
- **回归验证总闸**：所有阶段以 `make test` + `make eval` 为强制门禁，未全绿不合并。

---

*生成依据：前轮对 `agent-platform` 六维度代码调研 + GitHub 标杆项目（LangChain/Dify/AutoGen/CrewAI/OpenAI Agents SDK/DeepAgents）架构对比。本方案聚焦"借鉴而非重写"，所有改动均保留内部契约兼容。*
