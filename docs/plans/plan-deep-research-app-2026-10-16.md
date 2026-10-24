# deep_research 应用方案（第 7 个应用 · 多智能体长文研究报告）

> 状态：**方案稿，待确认后实施**（按 `AGENTS.md`「先方案后编码」，本文仅立方案，未动代码）
> 日期：2026-10-16
> 目标读者：本仓维护者
> 定位：在 monorepo `applications/` 下新增第 7 个独立可部署应用 **`deep_research`**，把「研究主题 → 结构化研究报告」做成平台一等能力。**核心不是新增运行时，而是新增一个 Planner 策略 + 一组 Skill 注册 + 一个 app 装配**：Planner / Skill / HITL / Checkpoint / ContextGovernor / 成本与轨迹治理全部从 `agent-runtime` 消费（遵守 `ARCHITECTURE.md` §4 红线 4「禁止再造 Runtime」）。
> 角色与流程设计**参考「深度研究团队」专家团**（6 角色 × 5 阶段 × 评审回路 × 研究参数卡 × 成员超时降级）——该设计的角色边界与评审回路已经过验证，本方案直接采用其**角色划分与质量控制语义**，仅替换实现载体。

---

## 0. 先读：两条前置结论

### 0.1 公共仓红线（本方案的第一约束）

本仓 `origin` = `github.com/Light-Towers/agent-platform`，**实测 `visibility: PUBLIC`**（`gh repo view`，2026-10-16）。因此：

| 约束 | 说明 |
|---|---|
| **禁写雇主内部信息** | 不得出现任何内部系统名、内部项目名、内部数据规模、内部账号/端点。数据通道一律表达为「可插拔适配器 + 环境变量」，实例值走 `.env`（已 gitignore），不入库 |
| **禁写来源于内部项目的量化数字** | 本方案所有指标位一律标 `⟦待实测⟧`，由本仓自己的评测跑出来回填；不得引用外部项目的口播数字 |
| **形态可对齐业界，耦合不可出现** | 「多智能体 + 质检回路 + HITL」是业界通用形态，可以写；与任何特定雇主的系统耦合不可写 |

> 实例化说明（**不写入本仓**）：真实部署时把检索/结构化通道指向实际服务即可，属 `.env` 配置层，不改代码。

### 0.2 能力复用结论：地基已在，缺的是「装配」不是「发明」

三档核对（看定义 → grep 调用点 → 看默认值）后的结论：

| 深研必需能力 | 平台既有件 | 接线状态（2026-10-16 实核） |
|---|---|---|
| Planner 决策 + 编排执行 | `agent-runtime/planner/protocol.py`（`Planner` / `Plan.mode` / `StreamEvent`） | ✅ 已接线（agent_server / agent_federation 在用） |
| 能力注册与组合治理 | `agent-runtime/skills/registry.py`（4 型 `SkillKind` + 组合校验 + 权限闭包） | ✅ 已接线 |
| **人工闸门（HITL 三路径）** | `agent-runtime/human_task.py`（`HumanTaskStore` / `HumanTaskResolver`） | ✅ **已接线（2026-10-15 三段链 WIRED）** |
| 断点续跑 / 挂起恢复 | `planner/durability*.py`、`awaitable_task*.py`、`execution_recovery.py`、`state_migration.py` | ⚠️ checkpoint/回调恢复已接线；`execution_recovery`（kill -9 自动续跑）**未接线** |
| 大产物卸载（上下文保纯） | `agent-runtime/payload_externalization.py` | ❌ **未接线**（`docs/TODO.md` §3） |
| 上下文治理 | `agent-runtime/context/`（governor / assembler / budget / compact / quality / validator） | ✅ 已接线 |
| 评测与轨迹 | `trajectory/`（store / store_pg / replay）、`forensic.py` | ✅ 已接线 |
| 成本与配额 | `cost_governance*.py`、`admission.py`、`execution_scheduler.py` | ⚠️ opt-in，`scheduler_enabled` 默认 `False`（V3 未验收，不得当已上线用） |
| 身份 / 多租户 | `identity.py` + `identity_middleware.py`（ADR-0006/0007） | ⚠️ 覆盖 2/6 应用；新应用**必须**一并装配，否则灰度末硬切换时漏接 |
| 统一 error 信封 / 可观测装配 | `agent_core.guardrails.app_factory.build_api_app` | ✅ 强制（P2 门禁） |

**⇒ 结论：deep_research 的工程量集中在「业务编排 + 质检契约 + 通道适配 + 装配与门禁」，而不是重造基础设施。** 未接线项（`payload_externalization` / `execution_recovery`）按第 8 节分期处理，**不在 P0 阻塞项内**。

### 0.3 参考来源与取舍（「深度研究团队」专家团）

| 决策 | 采纳 | 不采纳 |
|---|---|---|
| 角色划分 | ✅ 6 角色职责边界（编辑 / 研究员 / 审稿 / 修订 / 撰写 / 发布） | — |
| 流程 | ✅ 5 阶段 + 逐章评审回路 + 3 轮上限与强制通过 | — |
| 上下文共享 | ✅ 研究参数卡（只读卡，整张随调用传递） | — |
| 质量控制语义 | ✅ 6 维审查 + 硬性退回条件 + 交付终校五项 | — |
| 降级 | ✅ 成员超时 → 逐角色降级策略 + 显式通报 | — |
| **实现载体** | — | ❌ **不引入第二套团队运行时**（Agent Team 协议 / spawn 成员）：改为 Skill + `ExecutionGraph` + `runtime.delegate()`（红线 4）。专家团的「成员」= 本方案的「角色 Skill」；「主理人中转」= 编排层 hold 状态，**语义等价、载体不同** |

> 说明：专家团以「主理人 + 成员」的团队协议组织协作；本平台以「Planner + Skill 图」组织。两者在**职责划分与质量语义**上可 1:1 对应，但**不得**把团队协议原样搬进来当第二套运行时——平台已有 `SkillRegistry` / `ExecutionGraph` / `delegate` 组合治理，重复建设会触发红线 4 且破坏门禁。

---

## 1. 目标与非目标

### 1.1 目标

1. 输入一个研究主题，产出**结构化长文研究报告**（标题 / 目录 / 带引用正文 / 参考文献 + 引用编号）；
2. 具备**六层机制**：领域拆解（带验收标准）→ 多源并行检索 → 关键论断交叉核验 → 修订回路（有轮次上限）→ 结构化质检（硬性退回判据）→ 人工终审闸门；
3. **长任务可控**：SSE 进度推送、执行挂起与恢复、失败降级部分交付并显式声明数据缺口；
4. **多租户隔离**：`tenant_id` 为安全边界，全部业务表带隔离列；
5. **可评测**：分层评测（端到端产出质量 + 轨迹级判据）+ CI 可达的 golden 基线。

### 1.2 非目标（明确不做，防范围蔓延）

| 不做 | 原因 |
|---|---|
| 通用 DeepResearch 整车 | 平台定位是「工程化优先的多源证据运行时」，不是产品化研究 SaaS |
| 接入任何雇主内部系统 | 公共仓红线（§0.1）；通道以接口契约留位 |
| 模型微调 | 与平台「只换运行时不动权重」的既有命题不冲突，但不在本期 |
| **第二套执行引擎 / 第二套 HITL / 第二套 checkpoint** | `ARCHITECTURE.md` 红线 4；全部消费 `agent-runtime` |
| 依赖 V3 调度（`scheduler_enabled`） | 该开关默认 `False` 且端到端故障转移未验收，不得作为前置依赖 |
| 前端 SPA | 本期只交付 HTTP + SSE 契约；前端消费属本仓外 |

---

## 2. 定位与边界

### 2.1 与既有 6 个应用的关系

| 应用 | 形态 | 与 deep_research 的关系 |
|---|---|---|
| `agent_server` | 单进程 Supervisor，同步问答 | **互补**：它是「一问一答」，deep_research 是「一题一报告」（分钟级长任务） |
| `agent_federation` | 联邦网关 + 3 子服务编排 | **同族不同侧重**：两者都由 deepagents 谱系派生，但 federation 做「短任务路由编排」，deep_research 做「长任务工作流 + 质检回路」。**不得互相 import**（红线 2），只能经 HTTP + `shared-schemas` |
| `knowledge-service` | 通用知识库 RAG（:8900） | **被编排**：作为 `research.search.vector` 的 REMOTE 后端 |
| `nl2sql-service` | Text-to-SQL 数据分析 | **被编排**：作为 `research.search.structured` 的 REMOTE 后端 |
| `exhibition-agent` | 行业 Agent（skill_loader + 外部数仓 REST） | 无直接依赖；同为「领域应用」位 |

### 2.2 边界声明（写进 README，防叙事混淆）

- deep_research **不是** agent_federation 的升级版，也**不**接管其子服务；
- deep_research 的「五类专家角色」是**任务角色维度**；数据源是**工具/通道维度**——两者正交，不得混为一谈（同一角色可用多通道，同一通道可被多角色调用）；
- 外部检索能力（Tavily 等）以 REMOTE Skill 形式接入，**不做内置爬虫**。

---

## 3. 架构设计

### 3.1 分层落位

```text
applications/deep_research   ← 新增（独立可部署单元）
        ↓ 仅向下依赖
packages/agent-runtime       ← Planner / Skill / HITL / checkpoint / trajectory / context / cost
        ↓
packages/agent-core          ← tracing / logging / llm / guardrails / memory 门面 / intent
packages/shared-schemas      ← 跨进程契约（Request/Response/Event/SSE）
```

- 新应用**只向下依赖 `packages/`**；不得 `import agent_server.` / `agent_federation.`（红线 1、2）；
- 顶层包名 `deep_research` 全仓唯一（P5 门禁：workspace 成员间不得重复顶层包名）。

### 3.2 执行范式：主链路 WORKFLOW(graph)，叶节点局部 AGENTIC

依据 `planner/mode_selector.py` 的既定优先级（确定性/已注册 Workflow 优先 → 有界可组合进 Graph → 只有高不确定性开放式任务才进 Agentic）：

| 层 | 范式 | 理由 |
|---|---|---|
| 主链路（拆解 → 检索 → 核验 → 修订 → 撰写 → 质检 → 闸门） | **`mode="workflow"`**（`ExecutionGraph`，条件边） | 这是**稳定业务流程**，不应每次让 LLM 重新规划；且静态图天然无环，回路用条件边显式表达 |
| 单个「核验 / 撰写」子任务的内部执行 | **局部 `mode="agentic"`**（受 `max_steps` / `max_skill_depth` / 语义指纹护栏） | 子任务内容不确定，需要 LLM 自主选工具；护栏由 `PlannerRuntime.execution()` + `skill_guard` 承载 |
| 「该研究什么、拆几个子问题」 | **决策期 LLM + 确定性兜底** | `Planner.plan()` 契约要求无副作用可复现，LLM 失败须回退启发式 |

> **不做**：不把整个研究任务扔进 agentic 大循环——那是「单 Agent 想得久」，不是本方案要的「编排深度」。

### 3.3 角色分工与 Skill 清单（6 角色，设计参考「深度研究团队」专家团）

角色划分**参考「深度研究团队」专家团的已验证设计**（6 成员 × 5 阶段 × 评审回路 × 参数卡 × 超时降级）。**差异只在实现载体**：专家团以 Agent Team 协议 spawn 成员；本仓**不引入第二套团队运行时**（红线 4），改为把每个角色编译为一个 `Skill`，由 `ExecutionGraph` 编排、经 `runtime.delegate()` 受组合治理。

| 角色（参考） | Skill 名 | kind | boundary | 职责 | 契约要点 |
|---|---|---|---|---|---|
| 研究编辑 | `research.outline` | AGENT | INPROCESS | 主题 → 章节大纲（3–5 章，不重叠、逻辑递进） | 输出 JSON `{title, date, sections[]}`；**不含引言/结论/参考文献**（归 `research.framework`） |
| 课题研究员（模式一 初步调研） | `research.scout` | AGENT | INPROCESS | 广泛初调 → 研究摘要 + **来源池**（≥8–15 条） | 输出 `{summary, source_pool[]}`；来源池为跨阶段复用件 |
| 课题研究员（模式二 深度研究） | `research.draft` | AGENT | INPROCESS | 单章深度草稿 | ≥5 来源 / ≥3 类型（学术·机构·行业·媒体）；800–1500 字；**事实性陈述必带引用**；回传「新增来源清单」 |
| 草稿审稿人 | `research.review` | AGENT | INPROCESS | **6 维审查** → `PASS` / `REVISE` | 入参含 `current_round=N/3`；6 维＝来源充分性·事实准确性·观点均衡性·内容深度·结构清晰度·格式规范性；**第 3 轮强制 PASS** |
| 内容修订员 | `research.revise` | AGENT | INPROCESS | 逐条回应审稿意见 → 完整修订稿 + 修改说明 | **未受批评部分不动**；补充引用必须真实，**禁编造 URL** |
| 报告撰写人 | `research.framework` | AGENT | INPROCESS | 引言 / 结论 / 目录 / 参考文献（APA，去重排序） | 输出 JSON `{table_of_contents, introduction, conclusion, sources[]}` |
| 报告发布员 | `research.publish` | FUNCTION | INPROCESS | 整合 + 终校（格式/编号/链接/去重） | **不改研究内容**；遗留审稿警告汇总到「待完善事项」 |
| ——数据通道（3 个，**正交于角色维度**） | `research.search.web` / `.vector` / `.structured` | REMOTE | REMOTE | 公网 / 垂类语料 / 结构化取数 | 地址与 key 全走 env；只读语义；失败可降级 |
| ——人工闸门 | `research.outline_gate` / `research.publish_gate` | FUNCTION | INPROCESS | 大纲确认 / 交付终审 | 返回 `{"__awaitable__": True, "kind": "human", ...}`（走既有 HITL seam） |
| ——导出 | `research.export` | FUNCTION | INPROCESS | Markdown / PDF | 路径 containment 必过 `guardrails.fs`（P7） |

**两个维度必须分清**（写进 README，防叙事混淆）：

- **角色维度**（谁在什么职责边界上作业）→ 决定 **prompt 与上下文隔离**；
- **工具/通道维度**（信息从哪来）→ 决定 **工具集与失败降级**。

同一角色可用多通道，同一通道可被多角色调用。**不得把两者混为一谈**——这正是「专家子智能体」与「数据源子代理」最常见的混淆点。

**prompt 契约（每个角色 Skill 必带）**：

| 字段 | 作用 | 落点 |
|---|---|---|
| `description` | **给编排层看的路由依据**——写「何时用我」 | `Skill.description` → `to_tool_schema()` |
| `system_prompt` | **角色自己的作业规范**——写「怎么干活」（工作流 + 质量要求 + 输出形态） | `prompt/roles/<role>.yaml`（YAML 集中、`yaml.safe_load` 加载，防注入） |
| `input_schema` / `output_schema` | 输出契约，供编排层校验与串接 | `Skill.input_schema` / `output_schema` |
| `effect_contract` | 有副作用的角色（`publish` / `export`）声明 delivery/retry/recover | `Skill.effect_contract` |
| 轮次 / 超时 | 见 §3.11 | `Skill.timeout_ms` + graph 条件边 |

**副作用声明**：`research.publish` / `research.export` 与任何写外部系统的 Skill 必须声明 `effect_contract`，供执行图失败决策使用。

### 3.4 主执行图（5 阶段，对齐「深度研究团队」Workflow A）

```text
Phase 1 初步调研      research.scout ──▶ 研究摘要 + 来源池
        ↓
Phase 2 规划大纲      research.outline ──▶ [大纲人工确认闸门] ◀── HITL ①
        │                                   （快速模式省略；单章模式跳过 P2/P4）
        │  用户要求调整 → 回 research.outline 重规划
        ↓
Phase 3 逐章循环（每章，串行）
        ┌──────────────────────────────────────────────────┐
        │  research.draft ──▶ research.review ── PASS ──▶ 章节通过
        │                          │ REVISE
        │                          ▼
        │                   research.revise ──▶ 复审（回到 research.review）
        │                   （≤3 轮；第 3 轮强制 PASS + 章节末尾挂「审稿警告」）
        └──────────────────────────────────────────────────┘
        ↓  （章数 >5 且独立性强时可 fan-out 并行，所有副本共享同一参数卡）
Phase 4 报告框架      research.framework（引言 / 结论 / 目录 / 参考文献）
        ↓
Phase 5 发布          research.publish ──▶ [交付终审闸门] ◀── HITL ② ──▶ research.export
```

回路与护栏：

- **章节评审回路**：`draft → review → revise → review` 由条件边实现；`current_round` 由编排层**显式传入**；**第 3 轮强制 PASS**，未决问题 → 章节末尾「审稿警告」→ 报告末尾「待完善事项」；
- **两个人工闸门**（**注意：这是真实业务流程里的 HITL 需求，不只是「高风险工具」**）：
  - ① **大纲确认**（Phase 2）——用户在动工前校准方向，避免整篇跑偏；
  - ② **交付终审**（Phase 5）——可问责；
- 图深度/步数受 `PlannerRuntime(max_steps, max_skill_depth)` 约束；语义指纹（`enable_loop_fingerprint`）防「绕圈重复调用」；
- 任一检索通道失败 → 降级为**部分交付**并显式声明数据缺口（禁用公网信息冒充垂类结论）。

### 3.5 质检契约（`research.review` 6 维审查 + `research.publish` 终校）

**审查 6 维**（对齐专家团审稿标准，`research.review` 逐维判定）：

| 维度 | 判据 |
|---|---|
| 来源充分性 | ≥5 个不同来源，含超链接 |
| 事实准确性 | 事实性陈述均有来源支撑，无逻辑矛盾 |
| 观点均衡性 | 多元观点并陈，无单一来源偏见 |
| 内容深度 | 含具体数据 / 案例 / 分析，不停留表面 |
| 结构清晰度 | 论点 → 论据 → 分析 → 小结 逻辑通顺 |
| 格式规范性 | 引用格式 / 标题层级 / 表格格式统一 |

**硬性退回条件**（任一命中即 `REVISE`，不可豁免）：

1. 来源少于 3 个；
2. 存在**无来源的关键事实性陈述**；
3. 明显的事实错误或逻辑矛盾；
4. 内容严重偏离章节任务。

**轮次规则**：`current_round < 3` 可退回并给出**具体修改意见**；`current_round == 3` **即使发现问题也必须返回 PASS**，未决问题列入「遗留改进建议」→ 章节末尾挂「审稿警告」→ 报告末尾「待完善事项」。

**交付形态终校**（`research.publish`，五项）：格式规范化 / 章节编号连续 / 链接完整性 / 引用去重 / 术语一致性。

**失败兜底**：通道失败 → 部分交付 + 显式数据缺口声明；来源不足的结论降级为「待核实」；**禁编造来源**。

### 3.6 HITL 三路径 —— 直接消费既有 `human_task`（不新造）

本应用有**两个真实闸门需求**（不只是「高风险工具」）：① Phase 2 **大纲确认**（动工前校准方向）；② Phase 5 **交付终审**（可问责）。二者共用同一机制。

`agent-runtime/human_task.py` 已 WIRED（2026-10-15），三路径映射：

| 三路径 | 既有机制 |
|---|---|
| 人工审批 | `HumanTaskDecision.APPROVED` → `HumanTaskResolver.resolve_and_resume()` → `WAITING_HUMAN` → `RUNNING` |
| 编辑修正 | `options` 携带 `revise` + `resume_payload.comment` 回注（作为修订/重规划指令） |
| 拒绝执行 | `HumanTaskResolver.reject_and_fail()` → `ExecutionStatus.FAILED` |

装配要求：`PlannerRuntime(human_task_store=..., awaitable_task_store=...)` 注入；`HumanTaskStore` 基于 `AwaitableTaskStore`（PG 版）。**`approver` 恒取服务端断言主体，不接受请求体自报**（P12 + ADR-0007 口径）。

### 3.7 上下文治理

- **治理链**：`context/governor.py`（Select → Recall → Authorize → Validate → QualityScore）→ 治理后的 memory 列表注入 `PlannerContext.governed_memories`；
- **大产物卸载**：检索原文与中间产物落文件系统/对象存储，主流程汇总**只读摘要与路径**——P0 用应用层实现（写 `workspace_id` 隔离目录，路径经 `guardrails.fs` 校验）；待 `payload_externalization` 接线后**切换为消费平台件**（第 8 节 P2）；
- **摘要压缩**：超阈值时走 `context/compact.py`；
- **路径隔离**：目录由代码按任务 ID 生成（**不交给 LLM 自由命名**），校验走 `guardrails.fs`（P7 门禁）。

### 3.8 事件与出口

- 内部统一 `StreamEvent`（`protocol.py` 定义：`route / evidence / memory / answer / error / status / replan / suspended`）；
- 出口经 `serialize_stream_event()` + `shared_schemas.sse.sse_pack()` 打包，**与既有 SSE 客户端格式一致**；
- 出口事件不得回显异常消息/堆栈（P8 门禁）；
- 新增事件建议（**需在 shared-schemas 契约层定义**，不得 app 私自定义）：`research_subtask`（子任务进度）、`qc_finding`（质检发现）。

### 3.9 租户与身份

- `IdentityMiddleware` 必须挂载（`identity_middleware.py`），顺序**在 `SecurityGuardsMiddleware` 之后**且 guards 传 `subject_provider=get_asserted_tenant_context`（照 `agent_federation/api/identity_bridge.py` 的两条硬约束，并由等价 AST 用例锁住）；
- `tenant_id` 为安全边界，`workspace_id` 仅为归属维度，**不得单独承担隔离**（ADR-0006）；
- 每张业务表必含 `tenant_id`（`tests/governance/test_isolation_dimension_contract.py` 覆盖）。

### 3.10 研究参数卡（跨阶段上下文共享）

参考专家团的「研究参数卡」——**一张只读卡，每次调度角色都整张传入**，避免跨阶段信息丢失。落到平台：卡体存 `ExecutionContext.metadata["research_card"]`，经 `ContextGovernor` 治理后注入 `PlannerContext`，**不进对话历史存储**（防污染）。

```markdown
## 研究参数卡（只读）
### 基本信息
- 研究课题 / 报告语言 / 执行模式（完整|快速|单章）/ 时效窗口 / 输出格式 / 引用格式 / 用户特殊要求
### Phase 1 摘要（供下游复用）
{scout 摘要全文}
### 已收集来源池（避免重复检索）
1. [标题](URL) — 关键内容摘要
### 大纲（Phase 2 确认后填入）
### 已完成章节摘要（≤100 字/章）
```

**关键约束**：跨角色信息流**必须经编排层中转**，不得让 Skill 互相直连——这与平台既有契约「Skill → Skill 须经 `runtime.delegate()`」一致，不是额外设计。

### 3.11 成员超时与降级（参考专家团 maxTurns 表）

| 角色 Skill | 上限 | 超时降级 |
|---|---|---|
| `research.scout` | 80 轮 | Phase 1 超时：取已有部分结果继续；Phase 3 场景：标注「来源可能不充分」，强制进审稿 |
| `research.outline` | 20 轮 | 编排层基于 Phase 1 摘要生成简化大纲（3 章） |
| `research.draft` | 80 轮 | 同 `research.scout`（来源不足标注） |
| `research.review` | 20 轮 | 视为 PASS，记「审稿超时，未完成全量审查」 |
| `research.revise` | 30 轮 | 取当前版本为终稿 + 追加审稿警告 |
| `research.framework` | 30 轮 | 降级生成简化版引言 / 结论 |
| `research.publish` | 30 轮 | 编排层直接拼装（跳过终校） |

超时/降级**必须向用户显式通报**（角色名、降级方式、对质量的潜在影响），不得静默吞掉。实现载体：`Skill.timeout_ms` + 图级超时 + `execution_status` 记录。

### 3.12 路由与执行模式（对齐 `ModeSelector`）

| 用户意图 | 模式 | 编排 |
|---|---|---|
| 综合研究（默认） | **Workflow A**（完整） | 5 阶段全走，含 2 个人工闸门 |
| 「快速 / 简要 / 草稿即可」 | **Workflow B**（快速） | 跳过审稿修订回路；3 章；省略大纲确认；输出**显式标注**「本次为快速研究，未经审稿」 |
| 「只要某一章」 | **Workflow C**（单章） | 跳过 P2 / P4；参考文献由编排层从该章引用抽取 |
| 单动作（「查查 X」「审一下这段」） | **单 Skill 直调** | 经 `ModeSelector` 走 deterministic 单路由，不起整图 |

---

## 4. 数据模型（PG）

> 全部经 `agent_core.memory` / `agent_runtime.db` 单池（ADR-0003），阶段迁移走 `agent_runtime/migrations/`。

| 表 | 关键列 | 用途 |
|---|---|---|
| `research_tasks` | `tenant_id`(必)、`task_id`、`topic`、`status`、`workspace_id`、`created_at` | 研究任务主表（`status` 复用 `ExecutionStatus` 语义含 `WAITING_HUMAN`） |
| `research_sections` | `tenant_id`、`task_id`、`section_id`、`title`、`expected_points`、`round`、`status` | 大纲章节 + 每条评审轮次（`round` 即 `current_round`） |
| `research_sources` | `tenant_id`、`task_id`、`url_or_anchor`、`channel`、`fetched_at`、`content_hash` | 引用来源池（支撑「可溯源」判据 + 去重 + 跨章复用） |
| `research_review_findings` | `tenant_id`、`task_id`、`section_id`、`round`、`dimension`、`severity`、`claim_ref` | 6 维审查发现（退回判据留痕 →「待改进」/「待完善事项」来源） |
| `research_reports` | `tenant_id`、`task_id`、`version`、`markdown`、`refs[]`、`forced_pass` | 报告版本（含强制通过标记） |

复用平台既有表：`execution_queue` / `rate_limit_buckets` / `cost_records` / `trajectory` / `awaitable_tasks`（不新建平行表）。

---

## 5. 目录结构（拟）

```text
applications/deep_research/
├── pyproject.toml              # 成员包：deep-research-app；依赖 agent-core/shared-schemas/agent-runtime
├── README.md                   # 定位 + 诚实边界 + 与既有应用边界声明
├── Dockerfile
├── .env.example                # 全部开关 + 通道地址占位（无真实值）
├── deep_research/
│   ├── __init__.py
│   ├── main.py                 # 装配点：build_api_app + lifespan（PlannerRuntime / stores / identity 挂载）
│   ├── planner/
│   │   ├── research_planner.py # Planner 实现：plan() 拆解 + execute() 走 ExecutionGraph
│   │   ├── graph.py            # 5 阶段 ExecutionGraph（fan-out / 评审回路 / 两个闸门 / 条件边）
│   │   ├── card.py             # 研究参数卡：结构 + 更新规则（§3.10）
│   │   └── timeouts.py         # 角色超时与降级策略表（§3.11）
│   ├── skills/
│   │   ├── outline.py          # research.outline（章节规划，JSON 输出）
│   │   ├── scout.py            # research.scout（初调 + 来源池）
│   │   ├── draft.py            # research.draft（单章深度草稿）
│   │   ├── review.py           # research.review（6 维 + 硬性退回 + 3 轮强制通过）
│   │   ├── revise.py           # research.revise（逐条回应，输出完整修订稿）
│   │   ├── framework.py        # research.framework（引言/结论/目录/参考文献）
│   │   ├── publish.py          # research.publish（整合 + 终校，不改内容）
│   │   ├── search.py           # 三个检索 REMOTE Skill（地址走 env）
│   │   ├── gates.py            # outline_gate / publish_gate（__awaitable__ kind=human）
│   │   └── export.py           # md/pdf 导出（guardrails.fs containment）
│   ├── prompts/roles/          # 每角色一份提示词 YAML（description + system_prompt）
│   │   ├── outline.yaml  scout.yaml  draft.yaml
│   │   ├── review.yaml   revise.yaml
│   │   └── framework.yaml publish.yaml
│   ├── api/
│   │   ├── routers.py          # 任务/报告/审批端点
│   │   ├── stream.py           # SSE 出口（sse_pack + StreamEvent）
│   │   └── human_task.py       # 审批面（列待办/详情/approve/reject）
│   ├── store/                  # 第 4 节表的读写（含 tenant 校验）
│   └── config.py               # 类型化 env 解析（复用 agent_core.config）
├── tests/
│   ├── conftest.py
│   └── unit/                   # 组合校验 / 质检判据 / 回路轮次 / 租户隔离 / SSE 契约
└── evaluation/
    ├── golden.jsonl            # 端到端 golden（主题 → 结构断言，非逐字）
    └── run_eval.py             # 分层评测驱动
```

---

## 6. 接口契约

### 6.1 HTTP（全部经 `build_api_app` 装配，P2）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/research/tasks` | 创建研究任务（body: `topic`, `mode?`(full\|quick\|single_section), `time_window?`, `output_format?`, `citation_style?`）→ 返回 `task_id` |
| GET | `/api/research/tasks/{task_id}` | 任务状态（含 `WAITING_HUMAN` / `FAILED` / 章节级 `round`） |
| GET | `/api/research/tasks/{task_id}/stream` | SSE 进度（`StreamEvent` → `sse_pack`） |
| GET | `/api/research/tasks/{task_id}/report` | 取报告（Markdown / 来源池 / 「待完善事项」残留） |
| GET | `/api/research/tasks/{task_id}/human-tasks` | 列待办闸门（大纲确认 / 交付终审） |
| POST | `/api/research/tasks/{task_id}/human-tasks/{ht_id}/approve` | 审批通过（触发 resume） |
| POST | `/api/research/tasks/{task_id}/human-tasks/{ht_id}/reject` | 驳回（→ 执行失败） |

### 6.2 `shared-schemas` 新增 DTO（跨进程契约单一事实源，红线 5）

`ResearchTaskRequest` / `ResearchTaskStatus` / `ResearchReport` / `QCFinding` / `HumanTaskSummary`，以及 `sse.py` 的事件类型登记。**app 不得私自定义跨进程 DTO。**

---

## 7. 平台能力复用映射（需求 → 既有件 → 缺口与补齐）

| # | 需求 | 复用 | 缺口 / 本期动作 |
|---|---|---|---|
| 1 | 领域拆解（大纲 / 子问题 + 验收标准） | `Planner.plan()` + `research.outline` | **新写**（业务逻辑，属应用层） |
| 2 | 多源并行检索 | `SkillKind.REMOTE` + `ExecutionGraph` fan-out | **新写** 3 个通道 Skill（地址 env 化） |
| 3 | 上下文隔离（角色维度） | Skill 边界 + `context/` | 组装即隔离，无新代码 |
| 4 | 大产物卸载 | 应用层文件卸载（P0）→ `payload_externalization`（P2） | **平台件未接线**，先应用层兜住 |
| 5 | 交叉核验（6 维审查） | `SkillKind.AGENT` + `context/quality.py` 可参考 | **新写** `research.review`（硬性退回判据为业务规则） |
| 6 | 修订回路 + 3 轮上限 + 强制通过 | `ExecutionGraph` 条件边 | **新写**图定义（轮次由编排层显式传入） |
| 7 | 交付整合与终校 | `SkillKind.FUNCTION` | **新写** `research.publish`（不改研究内容） |
| 8 | HITL 三路径（大纲闸门 / 终审闸门） | `human_task.py`（已 WIRED） | **仅装配**（`human_task_store` 注入 + 审批面路由） |
| 9 | 跨阶段上下文共享（研究参数卡） | `ExecutionContext.metadata` + `ContextGovernor` | **新写**卡体结构（只读、不进历史） |
| 10 | 成员超时与降级 | `Skill.timeout_ms` + `execution_status` | **新写**策略表（§3.11） |
| 11 | 断点续跑 | checkpoint + 回调恢复 | **已接线**；kill -9 自动续跑（`execution_recovery`）**未接线**，降级为「可手动 resume」 |
| 12 | SSE 进度 | `serialize_stream_event` + `sse_pack` | **新增事件类型**（契约层） |
| 13 | 多租户隔离 | `identity_middleware` + `tenant_id` 契约 | **装配 + 表设计**（务必挂载，见 §3.9） |
| 14 | 限流 / 成本 | `admission` / `cost_governance` | opt-in，本期**只读不依赖**（`scheduler_enabled=False` 是平台自己的账） |
| 15 | 统一错误信封 | `build_api_app` | 强制，无缺口 |
| 16 | 观测 | `agent_core.tracing` + `init_tracing`（L-3 只许装配点初始化） | 装配 |
| 17 | 评测 | `trajectory/` + 分层评测 | **新写** golden set + 驱动 |
| 18 | 执行模式路由 | `planner/mode_selector.py` | 装配（§3.12 映射表） |

---

## 8. 实施分期与验收

> 每期独立可验收；**不跳期**。凡「声称完成」须 `make ci` 对齐（`AGENTS.md` 验证策略）。

### P0 · 端到端最小闭环（Workflow B 快速模式）
**交付**：app 骨架 + `research.scout` / `outline` / `draft` / `framework` / `publish` + 三通道检索 Skill + 研究参数卡 + SSE 出口 + 单测。
**验收**：给定主题 → 初调 → 大纲 → 逐章草稿 → 框架 → 发布，产出带引用的 Markdown 报告；SSE 事件完整；`make lint` + 本应用 pytest session 全绿。
**不做**：审稿修订回路、HITL 闸门。

### P1 · 审稿 → 修订 → 复审闭合（Workflow A 完整模式）
**交付**：`research.review`（6 维 + 硬性退回条件）/ `research.revise` + ExecutionGraph 条件边 + 3 轮上限与强制通过 + `research_sources` / `research_qc_findings` 落库。
**验收**：注入「无来源支撑」的论断**必被退回**；回路严格 ≤3 轮；第 3 轮强制 PASS 且残留进「待改进」→「待完善事项」；单测覆盖 6 维判据与轮次边界。

### P2 · HITL 双闸门 + 断点续跑 + 上下文卸载
**交付**：`research.outline_gate` / `research.publish_gate` + `human_task_store` / `awaitable_task_store` 注入 + 审批面路由 + 挂起/恢复链路；超时降级策略（§3.11）落地；大产物卸载切换为消费 `payload_externalization`（若届时仍未接线则登记为平台债）。
**验收**：Phase 2 大纲闸门可挂起为 `WAITING_HUMAN` → 审批/修正/驳回三分支均可达 → `RUNNING`/`FAILED`；重启后可 resume 未完成执行；超时降级有显式通报。

### P3 · 生产化
**交付**：限流/成本接线（若平台件已验收）、分层评测 golden、`docs/operations/` 运行手册、Dockerfile + compose。
**验收**：`make ci` 全绿；评测基线可复跑；运维手册含「换版本需重跑读数」的绑定口径。

---

## 9. CI / 门禁影响清单（**不做则 CI 红**）

| # | 项 | 动作 | 依据 |
|---|---|---|---|
| 1 | 根 `pyproject.toml` | `[tool.uv.workspace].members` + `[tool.uv.sources]` 增加新应用；按需加 extra | uv workspace |
| 2 | `Makefile` test 目标 | 新增本应用 pytest session（9 标准 → 10） | — |
| 3 | **`AGENTS.md` 的 session 计数** | 与 Makefile 同步（现称「10 个 pytest session」） | `check_doc_sync.py` 第 6 项会校验一致性 |
| 4 | `AGENTS.md` / `ARCHITECTURE.md` / `README.md` | 登记第 7 个应用（否则「6 应用」口径漂移，且文内引用路径存在性受校验） | `check_doc_sync.py` |
| 5 | `scripts/lint_architecture.py` | 新应用必须 `build_api_app`（P2）；不得裸 `FastAPI(`；禁直引 `@tool` 绕过 `get_tool`（P10）；不得裸调 `monitor.report_tool*`（P9） | 门禁 |
| 6 | P5 | 顶层包名 `deep_research` 唯一 | 门禁 |
| 7 | 路径 containment | 文件 I/O 走 `guardrails.fs`（P7） | 门禁 |
| 8 | 出口不回显异常 | SSE/JSON 帧不回显堆栈（P8） | 门禁 |
| 9 | 观测装配 | `init_tracing` 只在装配点（`main.py`）出现（L-3） | 门禁 |
| 10 | ruff 棘轮 | 新代码不得新增 `BLE001`/`S110` 盲捕获；如需白名单按**逐文件**登记 | `per-file-ignores` 棘轮 |
| 11 | **新增 ADR-0008** | 记录「新增第 7 应用 + 新 Planner 策略」决策（含为何走 workflow 而非 agentic） | `docs/adr/` 惯例 |
| 12 | governance tests | `tests/governance/` 的隔离维度、身份装配用例须覆盖新应用 | ADR-0006/0007 |

---

## 10. 风险与未决项

| # | 风险 / 未决 | 处置 |
|---|---|---|
| 1 | `payload_externalization` 未接线 | P0 应用层兜住；P2 切换并登记平台债 |
| 2 | `execution_recovery` 未接线 | P2 降级为「手动 resume」，不声称自动恢复 |
| 3 | `scheduler_enabled=False`（V3 未验收） | 本期不依赖调度；并发上限用应用层信号量（显式标注为**设计值非压测值**） |
| 4 | 身份中间件仅覆盖 2/6 应用 | 新应用必须一并装配（否则灰度末硬切换漏接） |
| 5 | 外部检索依赖（配额 / 可用性） | 超时 + 熔断 + 降级部分交付；无 key 时通道自禁用并显式声明 |
| 6 | 无 PG 环境下退化 | 走 InMemory 降级，仅用于单测冒烟，**不得作为生产形态声明** |
| 7 | 与 `agent_federation` 职责重叠的叙事混淆 | README 写死边界声明（§2.2） |
| 8 | **公共仓泄密** | §0.1 三条约束；`.env` 不入库；提交前人工过一遍「有无内部标识」 |
| 9 | 量化指标缺失 | 全部标 `⟦待实测⟧`，由本仓评测跑出后回填，**不得引用外部数字** |

---

## 11. 附：与「既有深研形态」的关系声明

本方案在**机制形态**上与业界同类深研系统对齐（多智能体角色分工 + 交叉核验 + 质检回路 + HITL 终审 + 断点续跑），这是公开的通用工程模式；但：

- 本应用是**平台自研的通用能力**，不针对任何特定行业语料、不绑定任何特定内部系统；
- 任何行业化实例化（语料库、结构化数据源、质检细则）属**部署配置**，不入本仓；
- 因此**不得**把本仓应用与任何雇主内部项目的代码/数字互相引用——两边是「同一模式的两个独立实现」，不构成同一套代码。

---

## 12. 下一步

1. 本方案确认后 → 建 ADR-0008 + P0 骨架（含 §9 门禁同步清单，一次做完否则 CI 红）；
2. P0 交付后跑一次端到端，把 `⟦待实测⟧` 指标位回填；
3. 逐期推进 P1 → P2 → P3。
