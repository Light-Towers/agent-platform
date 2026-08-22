# Agent Platform v2：完整 Agent Runtime 架构方案

> 状态：架构目标（Target Architecture）
> 适用分支：`v2`
> 文档性质：架构设计与演进基线，不等同于当前代码已全部实现。
>
> 本文基于当前 v2 已落地的 Planner / ExecutionGraph / PolicyValidator / SkillRegistry / Runtime / Context / Trajectory 能力，定义下一阶段的完整统一架构。目标不是继续堆叠组件，而是把 **模式选择、计划生成、策略治理、能力组合、执行运行时、Agentic 执行、Admission、Durability、Observability** 收敛到一套清晰的职责边界中。

---

## 1. 核心结论

Agent Platform v2 的最终核心抽象应当是：

```text
Request
  │
  ▼
Gateway / Admission
  │
  ▼
Mode Selector
  │
  ├── Deterministic
  ├── Static Workflow
  ├── Dynamic Graph
  └── Agentic
          │
          ▼
       Planner
          │
          ▼
         Plan
          │
          ▼
    Policy Validation
          │
          ▼
   Execution Runtime
          │
          ├── ExecutionGraph
          ├── SkillRegistry
          ├── Middleware
          ├── Budget / Deadline
          ├── Context / Memory
          ├── Checkpoint
          └── Event / Trace / Trajectory
```

最重要的架构原则是：

1. **Planner 只负责决定做什么，不负责直接执行能力。**
2. **所有可治理的执行最终进入统一 Runtime。**
3. **Skill 是能力层的一等公民，Function / Agent / Remote / Workflow 都是 Skill 的执行形态。**
4. **ExecutionGraph 是通用执行计划，而不是某一个框架的专属对象。**
5. **Static Workflow 可以编译为 Workflow Skill；Dynamic Graph 可以在运行时产生。**
6. **Agentic 不应长期拥有第二套 Runtime；Agentic 的 tool/subagent 调用最终应通过统一 Capability/Runtime 边界。**
7. **Admission 位于 Planner 之前，负责资源与并发准入；Policy 位于 Plan 之后，负责执行安全与组合约束。**
8. **Durability 是 Runtime 能力，而不是 Planner 的业务逻辑。**

---

## 2. 为什么需要四种执行模式

不同任务需要不同程度的确定性与自主性，不应强行统一成单一 Agent loop。

| 模式 | 适用场景 | 决策来源 | 执行结构 | 主要优势 |
|---|---|---|---|---|
| Deterministic | 简单问答、固定单能力 | 规则/确定性逻辑 | 单 Skill | 快、便宜、稳定 |
| Static Workflow | 已知业务流程 | 预定义 DAG | 固定 DAG | 可测试、可审计 |
| Dynamic Graph   | 多能力组合、依赖未知 | LLM Planner | 动态 DAG | 灵活且可治理 |
| Agentic | 开放式探索、复杂自主任务 | Agent loop | 动态 tool/subagent 调用 | 最大自主性 |

四者不是互相替代关系，而是同一个 Runtime 的不同计划来源。

---

## 3. 统一执行模型

### 3.1 Request → Admission

请求首先进入 Admission，而不是直接进入 Planner：

```text
Request
  │
  ▼
Auth / Session
  │
  ▼
Admission
  ├── authentication / authorization
  ├── rate limit
  ├── concurrency quota
  ├── per-user quota
  ├── priority
  └── queue / reject
```

Admission 只回答一个问题：**现在是否允许这个执行开始？**

它不负责判断用户问题应该调用哪个 Skill。

### 3.2 Mode Selector

准入成功后，由轻量级 Mode Selector 判断执行范式：

```text
Question + Context + Available Capabilities
                  │
                  ▼
             Mode Selector
                  │
       ┌──────────┼───────────┬──────────┐
       ▼          ▼           ▼          ▼
 deterministic  workflow     graph     agentic
```

Mode Selector 不应该生成完整 DAG；它只选择 Planner/Execution Mode。

优先采用：

1. 明确的静态规则优先；
2. 已注册 Workflow Skill 优先复用；
3. 可组合且边界明确的问题进入 Dynamic Graph；
4. 高不确定性、开放式探索任务才进入 Agentic。

这样可以避免所有问题都交给 Agent loop。

---

## 4. Planner 层

统一接口：

```python
plan(context) -> Plan
```

Planner 只产生声明式 Plan，不直接调用真实能力。

### 4.1 Plan

建议保持如下语义：

```text
Plan
├── mode
├── reason
├── sub_query
├── graph?
├── workflow_skill?
├── constraints
├── required_permissions
└── metadata
```

`Plan` 是执行意图，不是执行结果。

### 4.2 DeterministicPlanner

输出单 Skill / 单 route Plan。

```text
query → classify → known capability → Plan
```

### 4.3 WorkflowPlanner

优先发现已注册的 Workflow Skill：

```text
query
  ↓
Skill Discovery
  ↓
Workflow Skill
  ↓
Plan(workflow)
```

固定业务流程应尽量走这里，而不是重新让 LLM 规划。

### 4.4 Dynamic Graph Planner

这是 v2 后续最重要的能力之一：

```text
Query
  ↓
Skill Discovery
  ↓
Candidate Skills
  ↓
LLM Composition
  ↓
ExecutionGraph
```

LLM 只允许从候选 Skill 中选择，并输出结构化 Graph：

```text
Node
├── id
├── skill
├── input mapping
├── output mapping
└── metadata

Edge
├── dependency
└── condition
```

禁止模型直接生成任意 Python / 任意执行器。

### 4.5 Agentic Planner

Agentic 适合开放式任务，但其工具发现和调用必须逐步纳入统一 Skill/Runtime 边界。

第一阶段可以保持 DeepAgents 作为执行实现；第二阶段把其 tool/subagent 调用适配为 `SkillRegistry.execute()`；最终形成：

```text
Agentic Planner
      ↓
Agent Loop
      ↓
Skill Discovery
      ↓
SkillRegistry.execute()
      ↓
Unified Runtime
```

DeepAgents / LangGraph / 其他编排框架都只能作为执行实现，不应成为平台核心抽象。

---

## 5. ExecutionGraph

ExecutionGraph 是平台级执行 IR（Intermediate Representation）。

它至少应支持：

- 节点
- DAG dependency
- 条件分支
- 并行
- 输入映射
- 输出引用
- 节点权限
- 节点预算
- execution metadata

节点超时 / 节点重试策略 **不属于** Graph IR：执行级边界（超时 / 熔断 / retry）已在
`SkillRegistry.execute` 的 Middleware 洋葱链收敛（`GuardMiddleware` / `RetryMiddleware`），
ExecutionGraph 只声明结构、不内嵌执行边界。

示例：

```text
             ┌── search_company ──┐
Query ───────┤                     ├── analyze_revenue ──┐
             └── fetch_financial ─┘                     │
                                                        ▼
                                                 calculate_growth
                                                        │
                                                        ▼
                                                     answer
```

ExecutionGraph 不应该知道 LangGraph 的具体 API。LangGraph 可以是其中一个 executor。

---

## 6. Static Workflow → Workflow Skill

静态 DAG 应当能够被编译为 Skill：

```text
Workflow Definition
       ↓
Workflow Compiler
       ↓
Workflow Skill
       ↓
SkillRegistry
       ↓
Skill Discovery
```

因此：

> **Skill 不只是函数；Skill 是“可被 Planner 发现和调用的能力单元”。**

一个 Workflow Skill 内部可以继续使用 ExecutionGraph。

例如：

```text
financial_report_analysis
  kind = workflow
  input_schema = {...}
  output_schema = {...}
  executor = ExecutionGraphExecutor
```

这样静态 DAG 就拥有：

- discover
- permission
- input/output contract
- timeout
- retry
- circuit breaker
- tracing
- trajectory

等统一 Runtime 能力。

---

## 7. Skill 模型

Skill 应保持四类执行形态：

```text
Skill
├── Function
├── Agent
├── Remote
└── Workflow
```

统一契约：

```text
name
input_schema
output_schema
permissions
metadata
executor
```

### 7.1 Skill → Skill

Skill 组合不应通过 Python 直接互相调用，而应通过 Runtime/Registry：

```text
Skill A
  ↓
SkillRegistry.execute(B)
  ↓
Runtime
  ↓
Skill B
```

这样才能统一记录：

- call stack
- depth
- step budget
- permissions
- trace
- cost
- trajectory

Skill→Skill 应允许，但必须受到组合治理约束：

```text
max_depth
max_steps
cycle detection
permission
deadline
cost budget
```

---

## 8. Policy Validation

PolicyValidator 位于 Plan 与 Execution 之间：

```text
Plan
 ↓
PolicyValidator
 ↓
Validated Plan
 ↓
Runtime
```

至少检查：

1. Skill 是否存在；
2. permission 是否满足；
3. DAG 是否有环；
4. 最大节点数；
5. 最大深度；
6. 最大并行度；
7. 最大预算；
8. 是否允许当前 Workflow / Agent 组合；
9. 是否违反调用者级别的能力策略。

PolicyValidator 不执行 Skill。

---

## 9. Unified Runtime

所有可治理执行最终进入 Runtime：

```text
Runtime
├── ExecutionContext
├── Budget / Deadline
├── SkillRegistry
├── Middleware
├── Context / Memory
├── Checkpoint
├── EventBus
├── Trace
└── Trajectory
```

### 9.1 ExecutionContext

每次 execution 独立：

```text
execution_id
session_id
user_id
step_count
call_stack
deadline
budget
token_usage
cost
metadata
snapshot
trajectory
```

同一个进程中的不同请求不得共享可变执行计数器。

### 9.2 Middleware

统一执行边界：

```text
Admission
  ↓
Policy
  ↓
Runtime Middleware
  ├── timeout
  ├── retry
  ├── circuit breaker
  ├── rate limit / quota
  ├── result compression
  ├── tracing
  └── audit
  ↓
Executor
```

retry 应区分：

- 执行级 transient retry；
- Planner 级重新规划。

两者不能混为一谈。

---

## 10. Context / Memory

上下文分成四层：

```text
1. Conversation Context
   当前会话消息 / compacted summary

2. Execution Context
   当前执行预算、调用栈、trajectory

3. Working Context
   当前任务产生的 evidence / intermediate result

4. Long-term Memory
   跨 execution 的持久事实与历史
```

Tool result 过大时：

```text
Tool Result
   ├── small → context
   └── large → external store + reference
```

不要把所有历史和所有工具结果无限塞进 LLM context。

---

## 11. Durability

Durability 属于 Runtime，而不是 Planner：

```text
Execution
   ↓
Checkpoint
   ↓
Crash
   ↓
Resume
```

需要逐步支持：

- checkpoint
- replay
- resume
- idempotency key
- execution ownership
- stale execution recovery

单实例 `asyncio.Lock` 只能解决本进程并发；多副本环境需要 distributed lease / durable ownership。

---

## 12. Observability

所有执行模式必须输出统一事件模型：

```text
execution_started
plan_created
policy_validated
node_started
skill_called
tool_result
node_completed
checkpoint_saved
error
execution_completed
```

同一事件同时可以进入：

```text
EventBus
 ├── SSE / WebSocket
 ├── OpenTelemetry
 ├── Audit Log
 └── Trajectory Store
```

不要让每种 Planner 自己发一套不可兼容的事件。

---

## 13. Agentic 与 Graph 的最终关系

不是：

```text
Graph vs Agent
```

而应该是：

```text
                    Unified Runtime
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        ExecutionGraph          Agent Loop
              │                     │
              │              decides next action
              │                     │
              └──────────┬──────────┘
                         ▼
                   Skill Runtime
```

Agent 可以动态产生下一步动作；Graph 可以预先确定全部动作。

**两者共享同一能力层和治理层。**

这才是“自主性”和“可控性”真正共存的方式。

---

## 14. 最终目标架构图

```text
                                   ┌─────────────────────┐
                                   │        Client       │
                                   └──────────┬──────────┘
                                              │
                                              ▼
                                   ┌─────────────────────┐
                                   │ Gateway / Auth      │
                                   └──────────┬──────────┘
                                              │
                                              ▼
                                    ┌─────────────────────┐
                                    │ Admission           │
                                    │ quota/rate/priority │
                                    │ queue/reject        │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ SessionCoordinator  │
                                    │ session_id / dedupe │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                     ┌─────────────────────┐
                                     │ Mode Selector       │
                                     └──────────┬──────────┘
                                              │
                ┌─────────────────────────────┼─────────────────────────────┐
                │                             │                             │
                ▼                             ▼                             ▼
        Deterministic                 Workflow / Graph                  Agentic
          Planner                         Planner                        Planner
                │                             │                             │
                │                             ▼                             ▼
                │                       ExecutionGraph                  Agent Loop
                │                             │                             │
                └─────────────────────────────┼─────────────────────────────┘
                                              │
                                              ▼
                                       ┌─────────────┐
                                       │     Plan    │
                                       └──────┬──────┘
                                              │
                                              ▼
                                       ┌─────────────┐
                                       │   Policy    │
                                       │  Validator  │
                                       └──────┬──────┘
                                              │
                                              ▼
                                   ┌─────────────────────┐
                                   │ Unified Runtime     │
                                   │                     │
                                   │ ExecutionContext    │
                                   │ Budget / Deadline   │
                                   │ Middleware          │
                                   │ Checkpoint          │
                                   │ Context / Memory    │
                                   │ Event / Trace       │
                                   │ Trajectory          │
                                   └──────────┬──────────┘
                                              │
                                              ▼
                                   ┌─────────────────────┐
                                   │    SkillRegistry    │
                                   └──────────┬──────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
                Function                   Agent                    Remote
                    │                         │                         │
                    └─────────────────────────┼─────────────────────────┘
                                              │
                                              ▼
                                         Workflow
                                              │
                                              ▼
                                      ExecutionGraph
```

---

## 15. 当前 v2 → Target Architecture 差距

| 能力 | 当前 v2 | 目标 |
| --- | --- | --- |
| Planner 协议 | ✅ | 保持 |
| ExecutionGraph | ✅ | 升级为平台 IR |
| SkillRegistry | ✅ | 保持统一能力入口 |
| PolicyValidator | ✅ | 扩展预算/组合策略 |
| Skill Contract | ✅ | 完善 JSON Schema |
| Middleware | ✅ 已实现（2026-08-21） | retry（`RetryMiddleware` 瞬态重试）/ rate（`RateLimitMiddleware`+`SimpleTokenBucket`）/ audit（`AuditMiddleware`），均经 `SkillRegistry` 洋葱链生效 |
| Admission | ✅ 已实现收口（2026-08-21） | `agent_server/api/routes.py` 已作为所有 Planner 统一入口（enqueue→wait_for_admit→mark_completed）；另提供框架无关 `run_admitted`（`admission_gateway.py`）+ `InMemoryAdmissionController` 供联邦等复用 |
| Mode Selection | ✅ 已实现（2026-08-21） | 自动选择四种模式（ModeSelector + UnifiedPlanner，`PLANNER=auto`；保留 `PLANNER=` 强制 override） |
| Skill → Skill | ✅ 已实现（2026-08-21） | 一等公民组合模型（``Skill.sub_skills`` 声明）+ 运行时 ``skill_guard``（max_depth/max_steps/cycle）组合治理 + 计划期 ``CompositionValidator`` 静态校验（存在性 / 环 / 权限闭包）；经 ``runtime.delegate`` 编排 |
| Dynamic Graph | ✅ 已实现（2026-08-21） | LLM 多 Skill DAG（graph_compose 候选 Top-K + 结构化 Graph IR + 校验 + 失败重规划） |
| Static DAG → Workflow Skill | ✅ 已实现（2026-08-21） | 完整 compiler（compile_workflow + WorkflowExecutor，复用统一 Runtime） |
| Skill → Skill 运行时循环 / 语义指纹 | ✅ P5-1 已实现（默认关闭） | 完整运行时循环治理 |
| Agentic Runtime | ✅ 已实现收口 + deepagents 接入（2026-08-21） | 完全共享 Skill Runtime（tool discovery→SkillRegistry；tool call→`runtime.delegate`；subagent 作为 Agent Skill 经统一 Runtime）；联邦侧 `AGENTIC_RUNTIME_BRIDGE` opt-in 把联邦能力注册为 SkillRegistry 并追加「经统一 Runtime 治理」的 LangChain 桥接工具（`agentic_runtime_bridge.py`），默认关闭零影响 |
| Context Pipeline | ✅ | 统一四层 Context |
| Trajectory / Replay | ✅ 已实现（P3-1 / P3-2） | 与 Durable Execution 深度结合 |
| Distributed Session Ownership | ✅ 进程内已落地（2026-08-21） | InMemory 默认 + PgAdvisory lease（v2）+ ``ExecutionOwnershipStore``/``InMemoryExecutionOwnershipStore`` + ``reap_stale_executions``（stale recovery 检测 + 所有权回收，纯逻辑可单测）；**跨进程 durable recovery（PG LISTEN/NOTIFY 唤醒）属环境依赖，见 §17** |
| Durable Resume | ✅ 已实现（2026-08-21） | execution-level checkpoint/resume（checkpoint 集成进 ExecutionGraph，`_run_graph_in_place` 按节点落盘 + 同 execution_id resume） |
| Idempotency | ✅ 已实现（2026-08-21） | `with_idempotency` + `IdempotencyStore`/`InMemoryIdempotencyStore`（仅缓存成功；错误不污染） |
| Event Model | ✅ | 全模式统一 |

---

图例：

- ✅ = 已实现 / 完全支持
- 🟡 = 部分实现 / 规划中
- ❌ = 未实现 / 目标架构

## 16. 推荐实施顺序

### Phase A：先统一“选择”

1. 增加 Mode Selector；
2. 明确 Deterministic / Workflow / Graph / Agentic 的进入条件；
3. 保持 `PLANNER=` 配置作为强制 override，用于调试和灰度。

### Phase B：完成 Dynamic Graph

1. Skill Discovery Top-K；
2. LLM 输出结构化 Graph IR；
3. Graph schema 校验；
4. PolicyValidator；
5. ExecutionGraph executor；
6. 失败时重新规划，而不是直接进入无限 Agent loop。

### Phase C：Workflow Skill

1. 定义 Workflow DSL / Graph schema；
2. compiler → Workflow Skill；
3. 注册到 SkillRegistry；
4. discover 优先复用稳定 Workflow；
5. 为 Workflow 建 golden/eval。

### Phase D：Agentic Runtime 收口

1. DeepAgents tool discovery → SkillRegistry；
2. tool call → Runtime delegate；
3. subagent 作为 Agent Skill；
4. 统一 budget / permission / trace / trajectory；
5. 最终避免第二套执行治理体系。

### Phase E：生产级 Durability

1. Admission 与 execution ownership 解耦；
2. distributed lease；
3. checkpoint/resume；
4. idempotency；
5. stale execution recovery；
6. replay / audit。

---

## 17. 不建议做的事情

### 不要把 LangGraph 变成平台核心抽象

LangGraph 可以继续作为 Workflow/Graph executor，但平台核心应该是自己的 `Plan / ExecutionGraph / Skill / Runtime` 契约。

### 不要把 DeepAgents 变成平台核心抽象

DeepAgents 应该是 Agentic executor。未来可以替换成其他 Agent Loop，而不改变 Skill 与 Runtime。

### 不要所有任务都用 Agentic

开放式 Agent loop 的成本、延迟、不可预测性更高。已知流程应优先使用 Workflow/Graph。

### 不要让 Planner 直接调用 Python executor

否则 Policy / Budget / Trace / Retry / Audit 都会重新散落。

### 不要让 Skill 互相直接 import 调用

Skill→Skill 必须经过 Registry/Runtime，以保留治理和可观测性。

### 不要把所有历史放入 prompt

Conversation、Working Context、Long-term Memory、Tool Result 应分层管理。

---

## 18. 架构验收标准

完成 Target Architecture 后，应满足以下不变量：

1. **任何真实 Skill 执行都可以追溯到一个 `execution_id`。**
2. **任何 Skill 执行都经过统一权限、预算、超时和可观测性边界。**
3. **Planner 永远不能绕过 PolicyValidator 直接执行 Graph。**
4. **Agentic tool/subagent 执行不能绕过 Skill Runtime。**
5. **Static Workflow 与 Dynamic Graph 使用相同 ExecutionGraph IR。**
6. **Workflow 可以注册成 Skill，并被 Planner discover。**
7. **Skill→Skill 不允许绕过 Runtime。**
8. **同一个 execution 的 budget/step/call-stack 在 async 并发下隔离。**
9. **大结果不能无限进入 LLM context。**
10. **执行失败可以通过 trajectory + checkpoint 诊断或恢复。**
11. **Admission、Policy、Runtime 三层职责不能互相吞并。**
12. **更换 LangGraph / DeepAgents 不应改变平台核心 Plan/Skill/Runtime 契约。**

---

## 19. 最终架构判断

Agent Platform v2 不应该追求“一个万能 Agent”，而应该成为一个：

> **统一能力层 + 统一执行运行时 + 多种计划生成范式** 的 Agent Platform。

其中：

```text
Skill        = 能做什么
Plan         = 决定做什么
ExecutionGraph = 按什么结构做
Policy       = 是否允许这么做
Runtime      = 如何可靠地做
Admission    = 现在是否允许开始做
Trajectory   = 事后如何解释做过什么
Durability   = 中断后如何继续做
```

这套边界比“LangGraph Supervisor + DeepAgents”本身更重要。框架应该是实现，而不是架构。

---

## 20. 待环境验证任务（Environment-Dependent Backlog）

> 以下任务**无法在纯单元测试环境（无 PostgreSQL / 无真实 LLM / 单进程）内完成或验证**，
> 需要对应的外部依赖与部署形态。其**可单测的纯逻辑半程**已在本文档前述章节落地（✅），
> 此处仅记录「需环境验证/落地」的剩余部分，避免与已完成的代码混淆。
>
> **§20 生产级硬性验收约束（实现本节的硬性标准，缺一不可）**：多副本部署要「真正成立」，
> 不能只做到「能跑」。以下 5 条约束是 20.1–20.4 全部子项的统一验收基线，实现时逐条对照。
>
> - **C1 — 所有跨副本状态变更必须原子 CAS**：lease 抢占、slot 抢占、stale reap 一律用
>   `UPDATE … WHERE <owner=$me OR expires_at<now()> RETURNING` 的 compare-and-swap，
>   只有拿到 `RETURNING` 的副本才算成功。禁止「`SELECT` 判断 → `UPDATE` 写入」的非原子两步。
> - **C2 — PG = source of truth，LISTEN/NOTIFY = 唤醒信号（非消息队列）**：所有事实以 PG 表为准；
>   `NOTIFY` 仅用于「可能有事发生」的唤醒；等待方被唤醒后**必须回查 PG** 再决定动作，且带
>   periodic retry / reconcile 兜底——即使 `NOTIFY` 丢失、LISTEN 断连、Pod 重启、PG 抖动，
>   正确性仍不破坏。
> - **C3 — admission 是行级事实 + TTL，不是全局 counter**：`admission_slots` 每行一个占用
>   （`execution_id` / `owner` / `acquired_at` / `expires_at`），并发上限用 `COUNT(*)` +
>   带 TTL 自动过期；Pod crash 后其 slot 行随 TTL 自愈，不会被「`active=7` 减不回来」卡死。
>   slot 抢占同样走 C1 的 CAS（`COUNT < limit` 与 `INSERT` 不可分两步）。
> - **C4 — 生产模式 fail fast，不自动 fallback InMemory**：`distributed` 模式下若 `DATABASE_URL`
>   缺失 / 连接失败 → 启动即报错退出；**禁止**「DB 配错就静默退回 InMemory 多 Pod 各自维护状态」
>   的事故路径。`development` 模式才允许 InMemory。
> - **C5 — 测试必须覆盖四组**（见 §20.5）：单元语义、并发 CAS 正确性、kill-pod resume、NOTIFY
>   丢失后仍经 periodic reconcile 恢复。缺 D 组（NOTIFY 丢失）即视为未达标。
>
> **核心原则一句**：PG 保存事实，LISTEN/NOTIFY 负责唤醒，periodic reconciliation 保证最终一致性。

### 20.1 跨进程 durable recovery（multi-replica）
- **已落地（进程内，可单测）**：`ExecutionOwnershipStore` / `InMemoryExecutionOwnershipStore` /
  `reap_stale_executions` 完成 stale 检测 + 所有权回收；`AdmissionQueue` 的内存调度已落地。
- **待环境验证（按 C1/C2/C4）**：多副本下 ownership / 排队需跨进程协调。需新增持久化后端
  `PgExecutionOwnershipStore`，其 `acquire` / `reap_stale` 均走 C1 的原子 CAS：
  ```sql
  -- 抢占 lease（acquire / heartbeat 复用同构）
  UPDATE execution_leases
  SET owner = $2, expires_at = now() + ($3 || ' seconds')::interval
  WHERE execution_id = $1 AND (owner = $2 OR expires_at < now())
  RETURNING execution_id;
  -- 回收 stale：只有拿到 RETURNING 的副本有资格发 execution_resumable NOTIFY
  UPDATE execution_leases
  SET owner = NULL, expires_at = NULL
  WHERE execution_id = $1 AND expires_at < now()
  RETURNING execution_id;
  ```
  stale reaper 每副本起后台任务周期调用 `reap_stale_executions`（纯逻辑已在 durability.py:188
  落地），但回收动作本身必须 C1 CAS——**多副本同时发现 stale 也不会触发两次 resume**。
  `NOTIFY execution_resumable` 仅唤醒 resume loop，恢复流程为「唤醒 → 查 PG resumable →
  CAS acquire ownership → 从 checkpoint 恢复 → 继续」（C2），`NOTIFY` 丢失由 periodic scan 兜底。
- **依赖**：PostgreSQL + 多副本部署 + 多进程集成测试（§20.5 C/D 组）。

### 20.2 PG / Redis 后端持久化
- **已落地**：`InMemoryCheckpointStore` / `InMemoryIdempotencyStore` / `InMemoryAdmissionController`
  （测试 / 单进程默认后端）。
- **待环境验证（按 C1–C4）**：重启 / 多副本下 checkpoint、idempotency、admission 状态需持久化，
  避免丢失。新增 `PgCheckpointStore` / `PgIdempotencyStore` / `PgAdmissionController`（或 Redis
  等价物）并注入 `PlannerRuntime` / `run_admitted`。三个状态都属于**跨副本必须共享的执行事实**：
  | Store                       | PG 表                    | 关键语义               |
  | --------------------------- | ----------------------- | ---------------------- |
  | `PgCheckpointStore`         | `execution_checkpoints` | execution 的可恢复状态 |
  | `PgIdempotencyStore`        | `idempotency_keys`      | 防止重复执行            |
  | `PgExecutionOwnershipStore` | `execution_leases`      | 谁拥有 execution、何时过期 |
  - 实现必须保持原 ABC **语义完全不变**（仅后端替换）。
  - `admission_slots` 设计遵循 C3：行级占用 + TTL，`acquire` 走 CAS，非全局 counter。
  - 生产模式（C4）下 PG 缺失即 fail fast。
- **依赖**：PostgreSQL 或 Redis + 连接池配置 + 按 §20.5 的四组测试。

### 20.3 deepagents 桥接端到端灰度验证
- **已落地**：`AgenticRuntimeBridge` + 联邦侧 `AGENTIC_RUNTIME_BRIDGE` opt-in 适配器
  （默认关闭，零影响），单元层验证「桥接工具 → `runtime.delegate`」路由正确。
- **待环境验证**：开启开关后，**真实 LLM + 联邦部署**下验证 deep_agent 实际选择并调用桥接工具、
  统一治理（budget/permission/timeout/circuit/trace）在负载下生效、子智能体经统一 Runtime 执行。
- **依赖**：真实 LLM API Key + 联邦运行环境（非单测可覆盖）。

### 20.4 真多副本下的 Durability 全链路
- 综合 20.1 / 20.2：进程崩溃后由**另一副本**基于同一 `execution_id` 的持久化 checkpoint resume，
  跨进程 stale reaper（C1 CAS 防重复触发）唤醒 recovery（C2 信号 + 兜底）。需在多副本集成环境中
  做故障注入验证（§20.5 C 组：kill Pod A → lease expire → Pod B reap → CAS acquire → resume，
  断言不重跑 / 不丢 checkpoint / 不出现两 owner）。
- **依赖**：多副本部署 + 故障注入工具。

### 20.5 §20 验收测试矩阵（C5 展开）
- **A 组 — 单元语义**：Checkpoint CRUD、Idempotency CRUD、Lease acquire/renew/release/expiry、
  Admission acquire/release。用 fake pool 覆盖 PG 类语义（与 `test_session_lease.py` 同范式）。
- **B 组 — 并发正确性**：10 worker 同时 `acquire` 同一 execution → 成功者恰 1、失败者 9；
  `limit=5` 下 100 并发 admission → 任意时刻 `active <= 5`。验证 C1 的 CAS 不被绕过。
- **C 组 — 故障恢复**：Pod A 执行中 checkpoint → kill A → lease 过期 → Pod B 检测 stale →
  CAS acquire → resume；断言不从头执行、不执行两次、不丢 checkpoint、不出现两个 owner。
- **D 组 — 通知失效（极易漏，强制要求）**：人为丢弃 `NOTIFY` → 验证 periodic reconciliation
  仍能发现 vacancy / resumable execution 并最终恢复。不过此组即视为未达标（仍是「依赖通知才正确」）。

