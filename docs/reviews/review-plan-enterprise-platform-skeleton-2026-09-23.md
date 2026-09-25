# 方案评审报告：企业级智能平台骨架方案

> 评审对象：`docs/plans/plan-enterprise-platform-skeleton-2026-09-23.md`  
> 评审日期：2026-09-23  
> 评审人：Nox  
> 状态：<span style="color:red">**不建议按当前方案执行**</span>

---

## 1. 总体结论

该方案对当前架构的部分问题诊断正确（服务边界模糊、SkillKind 语义混淆、双重状态管理），但提出的核心架构选型——**将所有业务服务内嵌为单进程 asyncio 下的子 Agent 插件**——与企业生产级目标存在根本性冲突，且与当前已落地的 Plan-F（单 Runtime + 多 Planner）战略方向不一致。

**核心判断**：

1. **方向性错误**：Plan-F 明确“不统一 Agent，只统一 Runtime；不统一 Graph，统一 Capability”。本方案却要把 knowledge/nl2sql/kefu/exhibition 全部统一成“子 Agent 插件”，比 Plan-F 更激进，实际上是在统一部署形态，而非统一运行时隔层。
2. **生产级风险被系统性低估**：单进程架构下，故障隔离、资源隔离、依赖隔离、独立扩缩容、独立部署等生产级核心诉求均被忽略或轻描淡写。
3. **迁移复杂度被低估**：4 个独立服务有独立的 pyproject.toml、Dockerfile、入口点、配置、生命周期、测试体系，不是“低风险代码搬迁”。
4. **文档自相矛盾**：一边声称 `agent-runtime` 不动，一边要拆分其中的 `SkillRegistry`。

**建议**：当前方案不能直接进入执行阶段。应先回到 Plan-F 边界，把“统一 Runtime/Planner”与“是否合并部署形态”作为两个独立决策分别论证，而不是用后者替代前者。

---

## 2. P0 关键问题（阻止方案执行）

| # | 问题 | 具体说明 | 依据 / 后果 |
|---|------|---------|------------|
| P0-1 | **与 Plan-F 战略方向冲突** | Plan-F 核心原则是“统一 Runtime，不统一 Agent；统一 Capability，不统一 Graph”。本方案目标架构把所有业务 Agent 压进同一个进程，变成统一的子 Agent 层，实质是在统一 Agent 形态。 | 会推翻 2026-08-19 至 2026-09-21 已落地的 Phase 0–3 成果（Skill Registry、三执行器、Planner 协议、Workflow Skill 编译、组合治理）。 |
| P0-2 | **单进程架构违背企业生产级隔离原则** | 方案以“重依赖不成立”为由否定服务隔离，但服务隔离的核心价值不只是依赖隔离，还包括：故障隔离、资源隔离、独立部署、独立扩缩容、依赖版本隔离、回滚粒度、团队边界。单进程下一个子 Agent 的内存泄漏/死循环/C 扩展崩溃会拖垮整个平台。 | 企业级场景无法接受“升级 knowledge-service 必须重启整个平台”或“kefu 故障导致 nl2sql 不可用”。 |
| P0-3 | **对 asyncio 并发模型与第三方库 async 支持缺乏验证** | 方案假设所有子 Agent 操作都是 I/O 密集，asyncio 足够。但未验证：pymilvus 的 async API 成熟度、neo4j driver 的 async 路径、LangGraph/deepagents 在 asyncio 事件循环中的实际行为、CPU 密集型操作（如 embedding rerank、PDF 解析、tokenizer）对事件循环的阻塞影响。 | 任一同步阻塞点都会把多用户并发模型变成串行，且 Python asyncio 对 CPU 阻塞无自动抢占。 |
| P0-4 | **迁移风险被严重低估** | S1–S4 被标为“低风险（代码搬迁）”。实际上涉及：依赖合并/冲突、配置集中化、入口点删除、测试结构重组、生命周期管理改造、FastAPI lifespan 注入方式改变、各服务 DB schema/连接池统一、health/readiness 探针合并。 | 低估风险会导致进度失控，且“保留 agent-runtime 不变”与 R1“拆分 SkillRegistry”直接矛盾。 |
| P0-5 | **文档存在自相矛盾** | §4.3 和 §6 声称 `agent-runtime` / `shared-schemas` / `agent-core` 保留不变；但 §4.2 R1 要求“SkillRegistry 拆分为 SubAgentRegistry + ToolRegistry”，而 SkillRegistry 正位于 `agent-runtime` 内。 | 方案未说明 SkillRegistry 与现有 `agent_runtime/capabilities/registry.py` 的关系，也未解释是否要废弃当前已落地的 Capability/Skill 统一协议。 |

---

## 3. P1 重要问题（需补充或修正）

| # | 问题 | 具体说明 | 建议 |
|---|------|---------|------|
| P1-1 | **子 Agent vs Tool 边界不清晰** | 方案把 knowledge_query 列为子 Agent，rag 列为 Tool；但 RAG 本身不就是“检索 → rerank → 生成”的多步流程吗？与 knowledge 子 Agent 的边界在哪里？ | 给出更严格的判定标准：子 Agent = 维护私有状态空间 + 有内部决策循环（LLM 驱动或状态机）；Tool = 单次调用、无决策、无跨调用状态。若 RAG 无内部决策，应明确说明它如何与 knowledge 子 Agent 区分。 |
| P1-2 | **Remote Skill 价值判断片面** | 方案认为 Remote Skill 的“重依赖隔离”理由不成立，因而应取消 HTTP 调用。但 Remote 的价值还包括：独立演进、独立团队、独立 SLA、独立扩缩容、多语言实现、安全沙箱边界。 | 明确 Remote Executor 的保留场景，例如外部团队维护的能力、不可纳入同一 Python 依赖树的能力、需要独立部署的能力。 |
| P1-3 | **状态隔离与共享内存的张力未处理** | 方案声称“共享进程内存空间，但对话历史在 DB 不在内存（不互相污染）”。然而子 Agent 内部可能有内存缓存（如 BM25 索引、语义缓存、连接池、session 级状态），单进程下隔离更困难。 | 明确子 Agent 的内存/缓存隔离机制；是否需要按 workspace_id/session_id 隔离缓存键；是否禁止子 Agent 使用进程级全局可变状态。 |
| P1-4 | **缺少依赖冲突与版本管理策略** | 5 个应用服务当前各自有 pyproject.toml。合并为单进程后，所有依赖必须进入同一个 Python 解释器。torch/transformers/langchain/deepagents/pymilvus 等库版本冲突如何处理？ | 给出依赖合并方案：统一根 pyproject.toml？保持独立包但统一运行时？若统一，必须做依赖冲突矩阵和版本锁定。 |
| P1-5 | **配置与生命周期管理未设计** | 各服务原有独立 `.env.example`、Dockerfile、lifespan、health 探针。合并后配置如何注入？某个子 Agent 初始化失败是否影响整个平台启动？ | 设计统一配置 schema 和分级启动策略（核心子 Agent 失败则平台起不来，可选子 Agent 失败则降级）。 |
| P1-6 | **测试与 eval 验收标准不严谨** | “现有 1691 测试不退化”未说明该数字来源及是否包含各独立服务测试；合并后测试运行方式改变，可能产生 import 冲突。eval 15/15 是 Plan-F 当前基线，合并后未必等价。 | 明确 1691 的统计口径；设计合并后的测试策略；保留双跑 eval 基线作为行为漂移门禁。 |

---

## 4. P2 补充建议

| # | 建议 | 说明 |
|---|------|------|
| P2-1 | 补充量化分析 | 给出当前多服务部署的实际运维成本（部署次数、启动时间、资源占用、调用延迟），与单进程方案的预期收益做对比。 |
| P2-2 | 明确失败模式 | 列出单进程下每种故障场景（子 Agent 死循环、内存泄漏、CPU 阻塞、C 扩展崩溃、依赖初始化失败）的影响范围和缓解手段。 |
| P2-3 | 增加灰度与回滚策略 | 若坚持推进，必须设计按子 Agent 粒度的特性开关、灰度流量、热更新/冷更新策略，以及回滚到独立服务的逃生路径。 |
| P2-4 | 文档化架构决策记录 | 将“为什么从多服务转向单进程”与“为什么保留/取消 Remote”作为 ADR 写入 `docs/adr/`，并记录被否决的替代方案。 |
| P2-5 | 区分“统一 Runtime”与“统一部署形态” | 建议把两者解耦：先完成 Plan-F 的 Runtime 统一（已大部分完成），再独立评估是否需要合并部署形态，而不是合二为一。 |

---

## 5. gap → source 映射

| 方案论断 | 与事实的 gap | source / 证据 |
|---------|-------------|--------------|
| “当前是把业务逻辑和基础设施都当成了独立服务” | 部分正确，但忽略了服务作为独立演进边界的价值。 | `applications/` 下各服务有独立 pyproject.toml、Dockerfile、测试、入口点，本身就是部署边界。 |
| “Remote Skill 的‘重依赖隔离’理由不成立” | 仅论证了 pymilvus/neo4j driver 是轻量客户端，未论证依赖隔离、故障隔离、团队边界。 | Plan-F §4 Capability Registry 明确保留 Function / Agent / Remote 三执行器。 |
| “agent-runtime 保留不变” | 与 R1“拆分 SkillRegistry”矛盾。SkillRegistry 位于 `agent_runtime/skills/` 或 `agent_runtime/capabilities/`。 | `docs/plans/plan-f-single-runtime-multi-planner.md` §4.1 已落地 `agent_runtime/capabilities/registry.py` 作为 Skill Registry 雏形。 |
| “S1–S4 低风险（代码搬迁）” | 严重低估。涉及依赖、配置、生命周期、测试、入口点、部署脚本的全量重构。 | `applications/knowledge-service/`、`nl2sql-service/`、`kefu-service/`、`exhibition-agent/` 各有独立工程结构。 |
| “asyncio 天然支持多用户并发” | 仅在所有调用都是真正非阻塞异步时成立；未验证各子 Agent 的同步阻塞点。 | 需要逐个验证 pymilvus async、neo4j async、LangGraph 执行模型、deepagents 执行模型。 |
| “现有 1691 测试不退化” | 数字来源不明，且合并后测试运行方式改变。 | 需确认 `make test` 10 个 session 的数字是否等于 1691，以及合并后的等价性。 |

---

## 6. 维度覆盖率矩阵

评估该方案对企业生产级关键维度的覆盖情况：

| 维度 | 覆盖情况 | 说明 |
|------|---------|------|
| 故障隔离 | ❌ 未覆盖 | 单进程下子 Agent 故障会扩散到整个平台。 |
| 资源隔离 | ❌ 未覆盖 | 无 CPU/内存/连接池隔离设计。 |
| 依赖隔离 | ⚠️ 片面覆盖 | 仅论证客户端轻量，未处理版本冲突。 |
| 独立部署 | ❌ 未覆盖 | 子 Agent 更新需重启平台。 |
| 独立扩缩容 | ❌ 未覆盖 | 只能整体水平扩展，无法单独为 knowledge 扩容。 |
| 状态隔离 | ⚠️ 部分覆盖 | 提到对话历史在 DB，但未处理内存缓存/连接池隔离。 |
| 可观测性 | ⚠️ 默认继承 | Plan-F 已落地 tracing/otel，但单进程下需要更细粒度的子 Agent 维度指标。 |
| 并发模型 | ⚠️ 未充分验证 | asyncio 假设需要第三方库 async 支持实证。 |
| 回滚粒度 | ❌ 未覆盖 | 回滚从服务级退化为平台级。 |
| 团队边界 | ❌ 未覆盖 | 单进程代码库会提高团队间耦合。 |
| 安全边界 | ⚠️ 未覆盖 | sandbox 子进程保留，但子 Agent 进程内调用无沙箱。 |
| 与 Plan-F 一致性 | ❌ 冲突 | 违背“不统一 Agent，只统一 Runtime”的核心原则。 |

---

## 7. 可操作建议

### 7.1 立即停止当前方案执行

当前方案存在 P0 级方向性错误和生产级风险，不建议进入任何代码改造。

### 7.2 重新界定问题范围

将以下两个问题解耦，分别制定方案：

1. **Runtime/Planner 统一**：继续完成 Plan-F，已在 2026-09-21 完成大部分工作。
2. **部署形态优化**：如果运维成本确实高，应评估“是否减少服务数量”，而不是“是否压缩为单进程”。

### 7.3 替代方案建议

| 方案 | 说明 | 适用场景 |
|------|------|---------|
| **A. 保持当前 Plan-F 架构** | 统一 Runtime + 多 Planner，保留 Remote Executor 作为可选部署形态。 | 当前最稳妥路径。 |
| **B. 服务合并（非单进程）** | 将部分轻量服务合并为 fewer 服务（如 knowledge + nl2sql），但仍作为独立进程或至少独立容器运行。 | 当某些服务边界确实过细时。 |
| **C.  sidecar / 进程池模型** | 子 Agent 作为独立 worker 进程，由平台通过 IPC/消息队列调度；既保留 Runtime 统一，又保留隔离。 | 当需要统一调度又想保留故障隔离时。 |
| **D. 渐进式内嵌（高风险）** | 仅把确实无状态、无依赖冲突的轻量能力内嵌为进程内 Tool，保留有状态/重依赖能力为独立服务。 | 需严格前置 POC 和失败模式分析。 |

### 7.4 如坚持推进本方案，必须前置完成的工作

1. **POC 验证**：在隔离分支上把 knowledge-service 内嵌为进程内模块，跑压测验证 asyncio 无阻塞、内存隔离、故障传播范围。
2. **依赖冲突矩阵**：列出所有子 Agent 的依赖树，识别版本冲突。
3. **失败模式分析**：每个子 Agent 的异常如何被熔断/超时/隔离，不影响平台和其他子 Agent。
4. **ADR 文档**：记录“为什么放弃 Plan-F 的 Remote Executor”和“为什么接受单进程风险”。
5. **灰度与回滚方案**：保留独立服务的逃生路径。

---

## 8. 结论

该方案的问题诊断有价值，但架构选型方向与企业生产级要求及现有 Plan-F 战略不一致。建议**否决当前方案**，回到 Plan-F 边界，把“统一 Runtime/Planner”与“优化部署形态”作为两个独立问题分别论证，优先完成前者，再基于实际运维数据和 POC 结果决定后者。
