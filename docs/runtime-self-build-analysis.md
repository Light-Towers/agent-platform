# 自研 Runtime 动机分析与业界方案对比

> 研究对象：`agent-platform`（monorepo）的 `packages/agent-core`（零依赖运行时内核）与 `packages/agent-runtime`（运行时中间件 + Planner/Skill 协议）。
> 成文时间：2026-08-22。对比基线参考 2026 年主流 Agent 框架与云原生方案现状。

---

## 0. 结论先行（TL;DR）

本项目**不是"从零造轮子"**，而是把一套**框架无关的 Agent 可靠性原语**（`agent-core`）与其上的**执行治理层**（`agent-runtime`）自研实现，并把 LangGraph / DeepAgents 等**降级为"执行实现"而非运行时本身**（Plan-F 核心论断：*统一 Runtime，不统一 Agent*）。

自研的**核心动机**按权重排序为：

1. **厂商中立 + 框架无关**：`agent-core` 的 `dependencies=[]`，内核铁律"绝不 import langgraph/宿主"；任何编排框架（LangGraph / DeepAgents / AutoGen / CrewAI / 自研）都可作为 `Planner` 策略挂入。
2. **可控的生产级失败模式治理**：针对既往缺陷（懒加载竞态、降级不复位、会话劫持、微服务 SSE 连环 bug）逐一设防，retry/超时/熔断/取消/追踪的归属被显式划清（Plan-F R0）。
3. **合规与数据脱敏（PII）**：准入队列不存储问题全文、OTel 仅记长度+哈希、会话按密钥派生防劫持、跨用户回退禁止——这些是领域专属护栏，成熟框架开箱给不了。
4. **零依赖 + 零配置冒烟**：纯 stdlib 内核意味着极小攻击面、快冷启、易安全审计；`DATABASE_URL=` 空即可跑通。
5. **多部署轨收敛**：Plan-F 把两套并行编排（单进程 Supervisor / 联邦网关）收敛到"单 Runtime + 多 Planner"，降低双份维护成本。

**对业界方案的判断**：2026 年框架格局已收敛为七家（LangGraph / CrewAI / AutoGen / OpenAI Agents SDK / Google ADK / Microsoft Agent Framework / Claude Agent SDK）+ 三大云原生托管（AWS Bedrock AgentCore / Azure AI Foundry / Vertex AI Agent Builder）。行业共识是：**框架本身的重要性低于其上层的训练、沙箱与可观测性**，且多数生产系统是"确定性工作流 + 模型驱动 Agent"的混合体。

**建议**：本项目自研定位在受监管、需厂商中立、有基础设施基因的语境下是**合理且先进**的，不应推翻。真正的优化空间在——① 清理已观察到的代码债（见 §6.3）；② 对"商品化"能力（可观测、跨进程协议）优先借力成熟组件而非自研；③ 对非敏感负载引入云原生托管作为旁路部署目标。

---

## 1. 自研 Runtime 的结构与边界（基于代码实证）

### 1.1 `agent-core`：零依赖运行时内核

证据：`packages/agent-core/pyproject.toml` 中 `dependencies = []`；`README.md` 设计铁律"内核绝不 import `app.core.config` / `langgraph` 等宿主应用依赖；重型依赖全部 extra + lazy import"。

| 模块 | 公开能力 | 依赖策略 |
|------|---------|---------|
| `tracing` | `start_span` / `traced_span` / `user_query_hash` | 仅 stdlib（OTel 为 extra 懒导入） |
| `resilience` | `retry` / `retry_async` / `timeout` / `CircuitBreaker`（可插拔策略） | **纯 stdlib** |
| `guardrails` | `auth` / `ratelimit`（滑动窗口）/ `web`（Starlette 中间件） | 纯 stdlib；web 走 extra |
| `llm` | `BaseLLMProvider` 协议 + `register_provider` + `FallbackChatModel`（主备降级） | 协议层纯 stdlib；openai 适配器 extra |
| `memory` | `ConversationMemory` / `MemoryStore` 统一门面 / `embedder` / `vector_backend`（pgvector/milvus）/ `mongo` | base 纯 stdlib；各后端 extra |
| `tools` | `Tool` / `ToolRegistry` / `guarded_invoke` / `MCPToolAdapter` | base 纯 stdlib；mcp 适配器 extra |
| `events` | `EventBus` 多 sink 扇出 + `CallbackSink` / `OTelSpanSink`（异常隔离） | 纯 stdlib |
| `config` | `KernelConfig` + 类型化 env 解析 | 纯 stdlib |
| `intent` | L1 分类器（启发式 + LLM 兜底） | 纯 stdlib |
| `sql` | `guard`（sqlglot 白名单 + 方言参数化） | extra（sqlglot） |

**关键事实**：`agent-core` 并非从零发明，而是受开源包 `Light-Towers/reliable-agent` 启发后的**等价自研实现**（README §"上游内核蓝本"）。仓库内 `dependencies=[]`，无任何 `reliable-agent` pip 依赖；且本地是 superset（额外提供 `embedder` / `vector_backend` 语义记忆）。

### 1.2 `agent-runtime`：执行治理中间件 + Planner/Skill 协议

证据：`packages/agent-runtime/pyproject.toml` 仅依赖 `agent-core / shared-schemas / pydantic`；`docs/plans/plan-f-single-runtime-multi-planner.md`。

- **中间件层**：`admission`（持久化准入）、`coordinator`（会话并发协调）、`cache`（语义缓存）、`circuit_breaker`、`revert`（会话回退）、`mcp_client`、`otel`、`tracing`、`db`（连接池）。
- **Planner 协议**（`planner/protocol.py`）：`plan(ctx)->Plan`（决策）与 `execute(plan, runtime)->AsyncIterator[StreamEvent]`（执行）分离；`PlannerRuntime` 承载 `max_steps` / `max_depth` / token·cost 预算 + `skill_guard` 组合治理（步数/循环/深度/语义指纹）。
- **Skill 协议**（`skills/registry.py`）：`SkillRegistry` 统一注册/发现/执行；四种执行器 `Function` / `Agent` / `Remote` / `Workflow`；执行边界承载入参契约校验 + 统一超时 + 中间件洋葱链（熔断/重试）。
- **核心论断（Plan-F）**：*不要统一 Agent，统一 Runtime；不要统一 Graph，统一 Capability；不要统一决策方式，统一决策接口。* LangGraph / DeepAgents 仅是 `Skill` 的 `WORKFLOW` 执行实现，可替换。

### 1.3 最能体现"自研动机"的能力清单

| 能力 | 实现位置 | 体现动机 |
|------|---------|---------|
| 持久化准入（PG）+ 三维限流 + 优先级调度 + 崩溃恢复 | `agent-runtime/admission.py` | 可控性 / 合规（不存问题全文） |
| 会话并发协调（per-session 互斥 + coalesce/queue/reject） | `agent-runtime/coordinator.py` | 可控性 |
| 会话回退（checkpoint 原子回退 + 历史保留 + 跨用户禁止 + 审计） | `agent-runtime/revert.py` | 合规 / 可控性 |
| 可复位熔断器（连续失败 / 滑动窗口双策略，自动复位） | `agent-core/resilience.py` | 可控性 / 性能（防雪崩） |
| LLM 主备降级 + 结构化路由失败回退确定性启发式 | `agent-core/llm/*`、`app/agent/router.py` | 可控性 / 零配置 |
| OTel 追踪（W3C traceparent + 脱敏 + 可插拔 exporter） | `agent-runtime/otel.py` | 合规 / 可观测 |
| 语义缓存（余弦阈值命中跳过编排） | `agent-runtime/cache.py`、`agent-core/cache/*` | 性能 / 成本 |
| SQL 双保险（sqlglot 白名单 + 连接级只读） | `agent-core/sql/guard.py` | 合规 / 安全 |
| 会话防劫持（API_KEY 派生 thread_id，忽略客户端值） | `app/api/auth.py` | 合规 / 安全 |
| 执行所有权租约 + stale 回收（崩溃可恢复） | `planner/durability*.py` | 可控性 |
| 预算治理（max_steps/max_depth/tokens/cost + 语义循环指纹） | `planner/protocol.py` | 可控性 / 成本 |

---

## 2. 自研动机与技术背景（深度分析）

### 2.1 框架无关与厂商中立（Vendor Neutrality）

`agent-core` 的 `dependencies=[]` 与"绝不 import langgraph/宿主"铁律，意味着内核可在任意宿主（如 `zhanggui-zhiku` 的 `app` 包名场景）以 `import agent_core` 复用，不绑定任何 LLM 厂商或编排框架。Plan-F 把 LangGraph/DeepAgents 明确降级为"执行实现"，为未来替换 AutoGen/CrewAI/自研 Planner 留出门户。

> 对应行业共识（LangChain 官方博客，2026）："Most agentic systems are a combination of workflows and agents"，框架应是"orchestration framework + agent abstractions"而非绑定单一模型。自研内核正是这一哲学的落地。

### 2.2 可控的生产级失败模式治理

README「设计决策」表逐条列出既往缺陷与对策：懒加载无锁竞态 → `lifespan` 预热 + 连接池加锁；降级只置位不复位 → 熔断器冷却窗口自动复位；`asyncio.create_task` 无引用被 GC → 统一 `spawn_background`；客户端 `thread_id` 劫持 → 密钥派生；微服务适配层 SSE 连环 bug → 单进程多节点隔离。

这是**自研最硬的理由**：当 retry/超时/熔断/取消/追踪/流式的"归属"不清时，会出现 `retry(retry(agent(tool())))` 套娃（Plan-F R0）。自研把"决策"与"执行"分离——Planner 只决策不执行，retry/超时/熔断归 Runtime 的统一边界。成熟框架虽也提供这些，但**组合边界的精确控制**需要深入其内核，反而不如自研透明。

### 2.3 合规与数据脱敏（PII）

这是业界框架**普遍缺失**的领域专属护栏：

- **准入队列不存储问题全文**（`admission.py` 注释"脱敏约束"）：仅存元数据，崩溃恢复时标记 rejected 供客户端重试。
- **OTel 追踪脱敏**：仅记录问题长度 + SHA-256 前 16 位，不含全文（`README` 安全约定）。
- **会话防劫持**：`API_KEY` 启用时按密钥派生 `thread_id`，忽略客户端传入值。
- **跨用户回退禁止**：`revert.py` 硬约束。

对受监管行业（金融/医疗/政务），这类"可审计、可检视、可认证"的透明性是闭源平台/重型框架难以满足的。

### 2.4 性能与零配置

- 纯 stdlib 内核 → 极小攻击面、快冷启、易做安全审计。
- `DATABASE_URL=` 空即跑通（内存模式），所有能力 opt-in（README 快速开始）。
- 语义缓存命中跳过编排、上下文压缩、主备降级——均为成本/延迟优化。

### 2.5 多部署轨收敛（Plan-F）

背景（`plan-f` §1）：存在 `app/`（单进程 Supervisor）与 `agent_federation/`（联邦网关）两条独立部署轨，底层都是 LangGraph，但**编排层与外壳双份**，每次能力增强要改两处。Plan-F 把它们收敛到"单 Runtime + 多 Planner"，并把外壳（admission/coordinator/revert/SSE vs intent/cache/singleflight/rate_limit）**取并集迁入共享 `agent-runtime`**。这是**降低维护性**的自研驱动，而非性能驱动。

### 2.6 领域专属能力

Text-to-SQL 的 sqlglot 白名单 + 只读执行、RAG 的 BM25 + pgvector 混合检索 + RRF 融合、多租户语义记忆——这些是业务垂直能力，框架通常只给通用 RAG 抽象，深度定制仍需自研。

---

## 3. 业界替代方案现状（2026）

### 3.1 开源框架矩阵（来自 2026 横评）

| 框架 | 类型 | 主语言 | 生产成熟度 | 锁定风险 | 最佳场景 |
|------|------|--------|-----------|---------|---------|
| **LangGraph** | 状态图编排 | Py/TS | ★★★★★（生产首选） | 低–中（OSS 运行时） | 需 checkpoint/HITL/审计的复杂工作流 |
| **CrewAI** | 角色协作 | Py | ★★★★ | 中 | 多 Agent 业务协作、快速原型 |
| **AutoGen** | 对话式多 Agent | Py/.NET | 维护模式（不建议新项目） | 中→MS | 研究型多 Agent 辩论 |
| **OpenAI Agents SDK** | 厂商官方 | Py | ★★★★ | 中（OpenAI 绑定） | OpenAI 生态、handoffs、内置 tracing |
| **Google ADK** | 厂商官方 | Py/Java/Go/TS | ★★★★ | 高（Gemini/GCP） | GCP 原生、多模态 |
| **Microsoft Agent Framework** | 厂商官方 | .NET/Py | 2026 1.0 | 高（Azure） | Azure 企业 |
| **Claude Agent SDK** | 厂商官方 | Py/TS | ★★★★ | 高（Claude） | Claude 原生、coding agent |
| **PydanticAI** | 类型驱动 | Py | ★★★ | 低 | 强类型 Python 团队 |
| **DSPy** | Prompt 编译器 | Py | 研究向 | 低 | 优化 prompt/agent 管线 |
| **Mastra** | TS 优先 | TS | 上升期 | 低 | TS 全栈 |

基准参考（4-Agent Code Review 管线，2026）：可靠性 LangGraph 95% / OpenAI SDK 97%；延迟 LangGraph 38s / OpenAI SDK 34s；token 效率 LangGraph 比 CrewAI 省 15–18%。

### 3.2 云原生托管方案

| 方案 | 定位 | 关键能力 | 适用 |
|------|------|---------|------|
| **AWS Bedrock AgentCore** | "Agent 操作系统" | Runtime(8h 执行窗口)/Gateway/Policy(确定性 Cedar 强制)/Memory/Evaluations/Identity/Observability | 需企业级 SLA、托管基础设施 |
| **Azure AI Foundry Agent Service** | 多 Agent 编排 | 10k+ 模型路由、Guardrails、上下文隔离、任务委派 | Azure 生态企业 |
| **Vertex AI Agent Builder** | 低代码 + 开源栈 | 内置 LangChain/LangGraph/AG2、Cloud Functions/PubSub 集成 | GCP 原生、快速企业部署 |
| 开源 SDK 旁路 | Strands(AWS) / ADK(Google) / MAF(MS) | 模型驱动、MCP 原生、A2A 协议 | 想兼顾托管与自托管 |

### 3.3 行业共识

> "In 2026 the framework you pick matters less than the layer above it — training, sandboxing, and observability." — noderguru 2026 横评

> Anthropic / LangChain 共同观点：**多数生产系统是 workflow（确定性）+ agent（模型驱动）的混合**，应先选最简方案，仅在复杂度确实需要时升级；且"不要为简单任务引入 Agent 框架"。

---

## 4. 多维度对比

| 维度 | 本项目自研 Runtime | LangGraph 等开源框架 | 云原生托管（Bedrock/Foundry/Vertex） |
|------|-------------------|---------------------|--------------------------------------|
| **开发成本（初期）** | 高（需自建全套原语） | 中（API 即取，但需学图语义） | 低（配置即上线，数周→数天） |
| **维护成本** | 中–高（自担全部演进，但范围可控） | 中（跟社区，版本漂移风险） | 低（厂商负责基础设施） |
| **性能/延迟** | 优（纯 stdlib 内核、无抽象税、可精细优化） | 良（图开销小，token 效率最佳之一） | 中（托管层引入边界延迟，但弹性好） |
| **扩展性** | 良（单 Runtime 多 Planner，水平靠自管 PG/Redis） | 良（生态集成多，社区扩展） | 优（自动扩缩、8h 长任务、VPC/PrivateLink） |
| **可控性** | ★★★★★（retry/超时/熔断/取消归属自定） | ★★★★（可控但需深入内核） | ★★（配置项有限，底层不可改） |
| **合规/脱敏** | ★★★★★（PII 脱敏、可审计、自托管） | ★★★（需自接护栏） | ★★★★（厂商合规认证，但黑盒） |
| **厂商中立** | ★★★★★（零绑定） | ★★★★（OSS 多数中立） | ★（强绑定云厂商） |
| **可观测性** | 中（OTel opt-in、Langfuse 并存，仍在补强） | 优（LangSmith 成熟，或自接 OTel） | 优（托管 dashboard，但跨云不可移植） |
| **生态/集成** | 中（自研 MCP/适配器，A2A 待补） | 优（连接器丰富） | 优（云内原生集成） |
| **团队门槛** | 高（需 Agent 基础设施基因） | 中（图论/事件模型学习曲线） | 低（低代码/配置） |

---

## 5. 适用场景建议

### 5.1 决策矩阵

| 你的语境 | 推荐路径 |
|---------|---------|
| 受监管（金融/医疗/政务）、需厂商中立、有基础设施基因、多部署需收敛 | **保持自研 Runtime（本项目路径）** ✅ |
| 快速原型 / 演示 / 非核心业务（客服、内容审核） | 开源框架（CrewAI 起步，LangGraph 收口）或云原生托管 |
| 全在单一云生态、要企业 SLA 与合规认证、速度优先 | 云原生托管（Bedrock/Foundry/Vertex） |
| 单一模型厂商、最小代码量 | 厂商官方 SDK（OpenAI/ADK/Claude） |
| 强类型 Python 团队、结构化输出 | PydanticAI +（必要时）LangGraph 编排 |

### 5.2 本项目的定位判断

本项目**同时满足**"受监管倾向（PII 脱敏、跨用户隔离）""厂商中立（零依赖内核）""多部署收敛（Plan-F）""可控失败模式"四条，自研是**正确选择**，不应推翻。但应**避免对商品化能力过度自研**（见 §6）。

---

## 6. 迁移与优化路径

### 6.1 保持自研核心，开放策略接口（已具备，强化即可）

Plan-F 已把 LangGraph/DeepAgents 设计为可替换的 `Planner`/`WORKFLOW` 执行实现。建议：
- 在**非敏感负载**上试点把某个 `Planner` 用 OpenAI Agents SDK 或 Google ADK 实现，验证"Runtime 不变、引擎可换"的承诺，作为架构护城河的证据。
- 继续把 `app` 与 `agent_federation` 的编排收敛到红线 4（"禁止再造 Runtime"），减少双份维护。

### 6.2 商品化能力优先借力成熟组件（而非自研）

- **可观测性**：OTel 已 opt-in 且偏薄。建议深度接入 Langfuse/LangSmith 或成熟 OTel Collector 流水线，而非自建 trace 后端。
- **跨进程/跨 Agent 协议**：自研 `SkillRegistry` 的 `discover` 仍是关键词匹配（零依赖）。建议接入 **A2A（Agent-to-Agent）协议**与成熟 MCP 生态，避免重复造跨 Agent 通信轮子。
- **持久化/高可用**：`SessionCoordinator` 当前是 process-local 单实例（文档已标注"多副本下同一 session 串行不成立"）。多副本部署时应引入 **Postgres/Redis 分布式 lease 或 durable execution（如 Temporal / LangGraph Platform）**，而非自研分布式协调。

### 6.3 代码债清理（基于实读证据，建议优先）

实证发现的债，应在下一小版本清理：

1. **`resilience.py` 的 `CircuitBreaker.__init__` 存在重复字段赋值**（351–369 行把 `self._successes` / `self._failures_list` / `_window_size` 等重复赋值两次，且 `_half_open_probes` 映射逻辑含糊）。建议重构为单一初始化路径。
2. **`_LegacyCircuitBreaker` + `DeprecationWarning` 兼容层**：按计划在一个小版本后删除（AGENTS.md 已登记 WS-1~8 兼容期）。
3. **`Plan` / `PlannerContext` 字段重复与 `notes` 迁移债**：`Plan` 同时有 `question`（94 行）与 `notes`（deprecated）；`PlannerContext` 也有 `question` 重复定义（94 与 133 行）。应完成 `notes → ExecutionContext` 迁移并删除 deprecated 字段。
4. **`applications/agent_server`（schemas 已随包迁移） 对运行时类型的 re-export 兼容层**、`QueryRequest` 的 `AliasChoices("query","question")` 双写——统一入站字段名后移除。
5. **uv workspace 环境脆弱**（TB-3）：`uv sync` 默认只装根包会卸载 member 包，导致跨包测试失败。建议固化 `uv sync --all-packages` 或文档化 CI 必跑命令。

### 6.4 可选：云原生托管作为旁路部署

对**非敏感、弹性负载大**的负载（如公开问答、批量分析），可将同一套 `Skill` 通过 `Remote` 执行器桥接到 Bedrock AgentCore / Vertex Agent Engine，自研 Runtime 继续服务受监管核心。形成"核心自研 + 边缘托管"的混合架构（行业 hybrid 最佳实践）。

### 6.5 不要做的事（反模式）

- ❌ 推翻自研、全面迁移到某框架——会丢失 PII 脱敏/跨用户隔离/厂商中立等核心资产，且迁移本身高风险。
- ❌ 在简单场景引入完整 Runtime——对单轮 RAG/单次 LLM 调用，应走最简路径（项目已有 `EMBEDDING_MODE=auto` mock、零配置冒烟，契合此原则）。
- ❌ 重复造可观测/跨进程协议轮子——这些属商品化能力，借力优于自研。

---

## 7. 总结

本项目自研 Runtime 的工程决策**动机充分、架构先进**：以零依赖内核保证厂商中立与可控性，以"单 Runtime + 多 Planner"收敛多部署维护成本，以领域专属护栏满足合规诉求。在 2026 年框架/云原生高度成熟的背景下，它并非过时选择，而是**受监管、需中立、有基础设施基因团队的正确解**。

关键不在"自研 vs 框架"的二选一，而在**边界**：把核心可靠性/合规原语握在手里，把商品化能力（可观测、跨进程协议、分布式协调、边缘弹性）交给成熟生态。按 §6 的渐进路径执行，可在不推翻现有资产的前提下显著降低长期维护负担、提升扩展性。

---

## 附录：关键证据索引

| 论点 | 文件 |
|------|------|
| 零依赖内核 + 设计铁律 | `packages/agent-core/pyproject.toml`、`packages/agent-core/README.md` |
| 熔断双策略 + 自动复位 | `packages/agent-core/agent_core/resilience.py` |
| LLM 框架无关协议 | `packages/agent-core/agent_core/llm/protocols.py` |
| 统一事件出口（多 sink 异常隔离） | `packages/agent-core/agent_core/events.py` |
| Planner 决策/执行分离 + 预算治理 | `packages/agent-runtime/agent_runtime/planner/protocol.py` |
| Skill 注册表 + 四执行器 + 契约校验 | `packages/agent-runtime/agent_runtime/skills/registry.py` |
| 持久化准入（脱敏、三维限流） | `packages/agent-runtime/agent_runtime/admission.py` |
| Plan-F 单 Runtime 多 Planner | `docs/plans/plan-f-single-runtime-multi-planner.md` |
| 架构红线（禁止再造 Runtime） | `ARCHITECTURE.md` §4 |
| 设计决策（缺陷对策） | `README.md` §"设计决策" |
| 业界框架现状 | 2026 横评（noderguru / agentlist / app-lab / langchain blog / dragansr） |
