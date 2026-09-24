# Agent Platform V3

## Enterprise Agent Execution Platform

**版本：** V3
**定位：** 企业级 Agent Execution Platform
**状态：** Architecture Baseline
**适用范围：** 企业级 AI Agent、Multi-Agent、Tool、Workflow 及领域能力的统一运行与治理
**创建日期：** 2026-09-23

---

## 0. 本文件覆盖什么 / 不覆盖什么

### 覆盖

- Capability 语义模型（Tool / Agent / Workflow 定义与区分）
- Execution Boundary 抽象（InProcess / Remote / Sandbox）
- Scheduler 与并发治理概念框架（Admission / Concurrency Pool / Backpressure）
- Agent Runtime 分层与执行流程
- Reliability 概念（Checkpoint / Lease / Idempotency / Retry）
- ExecutionContext 与 Capability Contract 契约
- 会展业务映射示例

### 不覆盖（由其他文档承载）

| 不覆盖的内容 | 承载文档 | 说明 |
|-------------|---------|------|
| 8 层架构完整定义 + 十大缺口 P0 五项 | `docs/plans/plan-v3-execution-platform-final-architecture-2026-09-22.md` | 本文件是 8 层中 ①–④ 的语义展开，⑤–⑧ 见该文档 |
| V2 C1–C5 生产级验收约束 | `docs/architecture/complete-agent-runtime-architecture.md` §20 | 本文件继承而非替代，见 §42 |
| 仓库级依赖红线与 Application 边界 | `ARCHITECTURE.md` | 本文件不修改红线，与红线保持一致 |
| 7 域能力域划分与 milestone 依赖图 | `docs/plans/v3-roadmap-breakdown.md` | 7 域与 8 层是同一批能力的两种切法 |
| 具体实现代码与施工步骤 | 各 plan 文档 | 本文件是架构基线，非施工图 |

### 与 8 层总纲的映射

`plan-v3-execution-platform-final-architecture-2026-09-22.md` 定义了 8 层架构与十大缺口。本文件覆盖关系：

| 8 层 | 名称 | 本文件覆盖？ | 对应章节 |
|------|------|------------|---------|
| ① | Execution Kernel | 部分（概念） | §9 Checkpoint / §22 Lease |
| ② | Execution Semantics | 部分（概念） | §11 Capability Contract / §21 Idempotency |
| ③ | Execution Scheduler | 部分（概念） | §16–§20 Scheduler / Admission / Backpressure |
| ④ | Agent Runtime | **是** | §5–§7 总体架构 / Runtime / §28 Registry |
| ⑤ | Execution Observability | 否 | 见 8 层总纲 |
| ⑥ | Control Plane | 否 | 见 8 层总纲 |
| ⑦ | Governance Plane | 部分（§40 安全边界） | 8 层总纲为母 |
| ⑧ | Storage / Scale Plane | 否 | 见 8 层总纲 |

**P0 五项缺口（均不在本文件范围内）**：

1. 严格 Fencing Generation — 8 层总纲缺口 1
2. Effect Contract — 8 层总纲缺口 2
3. External Task + Receipt — 8 层总纲缺口 3
4. Execution Scheduler（完整 Dispatch/Queue/Worker） — 8 层总纲缺口 4
5. Durable Execution Status State Machine — 8 层总纲缺口 5

> **本文件是 8 层中 ④ Agent Runtime 的语义展开 + ①②③ 的概念框架，不是 V3 全部。**

---

# 1. 架构目标

Agent Platform V3 不以"提供一个 Agent 框架"为主要目标，而是提供一个能够承载企业 Agent 长期运行的 **Execution Platform**。

核心解决：

1. Agent 如何执行
2. 多个 Agent / Execution 如何并发运行
3. Execution 如何可靠恢复
4. Capability 如何统一注册和调用
5. Capability 是否需要独立进程
6. 如何控制不同 Capability 的并发和资源
7. 如何实现 Tool / Agent / Workflow 的统一执行
8. 如何支持 In-Process / Remote / Sandbox 混合部署
9. 如何统一 Tenant、Auth、Trace、Timeout、Retry、Idempotency
10. 如何在复杂业务中支持动态 Agent 和 Multi-Agent

平台不试图解决所有业务问题。

业务能力属于 Application / Capability 层。

平台负责：

> **Execution、Scheduling、State、Reliability、Governance。**

---

# 2. 核心设计原则

## 2.1 Capability 与部署边界解耦

最重要的设计原则：

> **Capability 的语义和 Capability 的运行位置是两个不同的问题。**

不能因为一个能力是 Agent，就认为它必须是独立服务。

也不能因为一个能力是 Tool，就认为它必须在当前进程执行。

因此：

```text
Capability
   │
   ├── Tool
   ├── Agent
   └── Workflow
          │
          ↓
   Execution Boundary
          │
   ├── InProcess
   ├── Remote
   └── Sandbox
```

四种组合都是合法的：

```text
Tool  + InProcess
Tool  + Remote

Agent + InProcess
Agent + Remote
```

---

# 3. Capability 模型

Capability 是平台统一识别和执行的最小业务能力单元。

Capability 不等于 Service，也不等于 Agent。

## 3.1 Tool

Tool 表示一个相对确定的能力。

调用者决定：

> "我要执行什么操作。"

例如：

```text
get_exhibition()
search_exhibitors()
query_booth()
create_booth_order()
search_knowledge()
```

Tool 内部可以存在多个步骤。

因此：

> Tool ≠ 单函数。

Tool 的关键特征是：

> **调用者控制具体操作语义。**

---

# 3.2 Agent

Agent 表示一个被委托的目标。

调用者只提供：

```text
goal
context
constraints
```

Agent 自己决定：

```text
下一步做什么
调用什么 Capability
是否继续执行
是否重新规划
什么时候结束
```

例如：

```text
目标：
分析上海展会招商情况

Agent：
1. 查询展会
2. 判断需要哪些数据
3. 查询招商数据
4. 发现数据不足
5. 调整查询
6. 分析行业
7. 生成报告
```

Agent 的核心不是"有没有 LLM"。

而是：

> **下一步由 Agent 根据 State 和环境反馈动态决定。**

---

# 3.3 Workflow

Workflow 表示预先定义的执行结构。

例如：

```text
A → B → C → D
```

或者：

```text
A
├── B
├── C
└── D
    ↓
    E
```

Workflow 可以包含 Agent / Tool。

Workflow 的特点是：

> **结构主要由系统预先定义。**

Agent 的特点是：

> **下一步主要由运行时决策。**

两者可以组合：

```text
Workflow
   ↓
Agent
   ↓
Tool
```

---

# 4. Agent Definition / Agent Run / Execution

必须区分三个概念。

## 4.1 Agent Definition

Agent Definition 是静态定义。

例如：

```text
ExhibitionAnalysisAgent
```

包含：

```text
name
description
capabilities
policies
state_schema
model_config
limits
```

它类似：

> Agent Class / Agent Blueprint

---

# 4.2 Agent Run

Agent Run 是一次具体 Agent 工作。

例如：

```text
agent_run_id = ar_10001
```

包含：

```text
execution_id
session_id
tenant_id
user_id
goal
context
state
budget
deadline
```

---

# 4.3 Execution

Execution 是 Runtime 实际调度和执行的单位。

```text
Agent Definition
       ↓
    Agent Run
       ↓
    Execution
       ↓
Capability Execution
```

因此：

> asyncio Task 只是 Execution 的一种实现方式，不应该成为 Agent 的定义。

---

# 5. 总体架构

```text
                         Client
                           │
                           ↓
                    API / Gateway
                           │
                           ↓
                  ┌─────────────────┐
                  │   Agent Runtime │
                  │                 │
                  │ Intent / Plan   │
                  │ State           │
                  │ Scheduler       │
                  │ Execution       │
                  │ Reliability     │
                  │ Governance      │
                  └────────┬────────┘
                           │
                    Capability
                       Registry
                           │
             ┌─────────────┼─────────────┐
             │             │             │
            Tool          Agent       Workflow
             │             │             │
             └─────────────┼─────────────┘
                           │
                   Execution Router
                           │
          ┌────────────────┼────────────────┐
          │                │                │
      InProcess          Remote          Sandbox
          │                │                │
          ↓                ↓                ↓
     Local Runtime    Domain Service    Isolated Runtime
          │                │                │
     DB / API / LLM    Knowledge/NL2SQL   User Code
```

---

# 6. Runtime 分层

Runtime 分成六个核心层。

```text
┌─────────────────────────────────────┐
│             Agent Layer             │
│ Intent / Planning / Decision        │
├─────────────────────────────────────┤
│          Capability Layer           │
│ Tool / Agent / Workflow             │
├─────────────────────────────────────┤
│          Scheduler Layer            │
│ Admission / Concurrency / Backpress │
├─────────────────────────────────────┤
│          Execution Layer            │
│ InProcess / Remote / Sandbox       │
├─────────────────────────────────────┤
│        Reliability Layer            │
│ Checkpoint / Lease / Retry / Idemp │
├─────────────────────────────────────┤
│        Infrastructure Layer        │
│ PostgreSQL / Redis / Queue / Model │
└─────────────────────────────────────┘
```

---

# 7. Agent Runtime

Agent Runtime 是平台核心。

它负责：

```text
Task
 ↓
Understand
 ↓
Plan
 ↓
Select Capability
 ↓
Schedule
 ↓
Execute
 ↓
Observe
 ↓
Update State
 ↓
Next Decision
 ↓
Terminal
```

Runtime 不应该直接包含具体业务逻辑。

例如：

```text
Runtime
 ├── 不知道什么是展会
 ├── 不知道什么是展商
 ├── 不知道什么是展位
 └── 不负责业务规则
```

这些属于 Domain Capability。

---

# 8. State

State 是 Execution 当前运行状态。

例如：

```json
{
  "execution_id": "ex_10001",
  "goal": "分析上海展会招商情况",
  "current_step": "industry_analysis",
  "tool_results": {},
  "agent_sessions": {},
  "observations": [],
  "budget": {},
  "status": "RUNNING"
}
```

State 用于：

> **决定下一步。**

---

# 9. Checkpoint

Checkpoint 是 State 的持久化快照。

```text
State
   ↓
Checkpoint
   ↓
PostgreSQL
```

Checkpoint 解决：

> Execution 崩溃后如何恢复。

恢复不是恢复原来的 asyncio 调用栈。

而是：

```text
读取最新 Checkpoint
       ↓
恢复 Execution State
       ↓
重新驱动 Execution Graph
       ↓
继续执行
```

---

# 10. Execution Context

所有 Capability 执行必须携带统一 ExecutionContext。

建议至少包含：

```text
ExecutionContext
├── execution_id
├── agent_run_id
├── session_id
├── tenant_id
├── user_id
├── principal
├── authorization_context
├── trace_id
├── workspace_id
├── deadline
├── budget
├── cancellation_token
└── metadata
```

禁止 Capability 自己从任意参数中决定：

```text
tenant
user
permission
```

这些必须来自可信 Runtime Context。

---

# 11. Capability Contract

所有 Capability 必须遵循统一 Contract。

```text
Capability
├── identity
├── description
├── input_schema
├── output_schema
├── state_schema
├── error_model
├── timeout
├── retry_policy
├── idempotency
├── cancellation
├── auth_policy
├── tenant_policy
└── execution_policy
```

例如：

```text
knowledge.search

Input:
  query
  filters

Output:
  documents[]

Timeout:
  10s

Retry:
  2

Idempotency:
  read-only

Execution:
  Remote
```

这样 Runtime 才可以统一治理。

---

# 12. Execution Boundary

Capability 注册之后，由 Execution Router 决定在哪里执行。

```text
Capability
      ↓
Execution Router
      │
      ├── InProcessExecutor
      ├── RemoteExecutor
      └── SandboxExecutor
```

---

# 13. InProcess Executor

适合：

- 轻量 Tool
- 纯 I/O
- 简单业务逻辑
- 轻量 Agent
- 不需要独立资源池
- 不需要强故障隔离

例如：

```text
get_exhibition()
get_exhibitor()
calculate_booth_area()
simple_validation()
```

优点：

```text
低延迟
低序列化成本
调用简单
```

缺点：

```text
共享进程故障域
共享资源
无法独立扩缩容
```

---

# 14. Remote Executor

适合：

- 重依赖
- CPU 密集
- GPU
- 模型推理
- 独立扩缩容
- 独立发布
- 强故障隔离
- 独立资源池

例如：

```text
Knowledge Service
NL2SQL Service
Model Service
Document Processing
```

Remote 不代表：

> Agent。

Remote 只是：

> **Execution Boundary。**

---

# 15. Sandbox Executor

适合：

```text
用户代码
Python 执行
SQL
Shell
不可信脚本
实验性能力
```

要求：

```text
进程隔离
资源限制
超时
文件系统隔离
网络策略
权限控制
```

---

# 16. Scheduler

Scheduler 是 V3 相比 V2 应进一步补强的核心。

它解决：

> "很多 Execution 同时到来时，哪些现在执行，哪些等待？"

---

# 17. Admission Control

首先控制是否允许 Execution 进入运行态。

例如：

```text
Global:
max_execution = 100

Tenant:
max_execution = 20

Agent:
max_execution = 10

Capability:
max_concurrency = 30
```

超过限制：

```text
RUNNING
   ↓
QUEUED
```

而不是继续创建无限任务。

---

# 18. Capability Concurrency Pool

不同 Capability 使用不同资源池。

```text
                 Scheduler
                     │
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
    LLM Pool       SQL Pool      RAG Pool
       │             │             │
    max=50         max=10        max=20
```

原因：

不同能力的资源消耗不同。

例如：

```text
get_exhibition()
```

可能只是一次 DB 查询。

而：

```text
NL2SQL
```

可能涉及：

```text
LLM
SQL
数据库
Schema Retrieval
结果验证
```

不能共享同一个并发限制。

---

# 19. Backpressure

系统必须允许：

```text
Producer > Consumer
```

时进行背压。

例如：

```text
Agent
  ↓
Scheduler
  ↓
Queue
  ↓
Capability
```

而不是：

```text
Agent
  ↓
无限 asyncio.create_task()
```

否则高峰期可能出现：

```text
LLM 请求暴增
DB 连接池耗尽
CPU 飙升
Memory 增长
请求超时
Retry Storm
```

最终形成级联故障。

---

# 20. Retry 与 Backpressure 必须联合设计

不能简单：

```text
失败
 ↓
Retry 3 次
```

因为高并发情况下：

```text
100 请求失败
 ↓
300 Retry
 ↓
资源压力更大
 ↓
更多失败
 ↓
Retry Storm
```

因此：

```text
Timeout
 ↓
Retry Policy
 ↓
Circuit Breaker
 ↓
Backpressure
 ↓
Admission Control
```

必须协同。

---

# 21. Idempotency

对于具有副作用的 Capability：

```text
create_booth_order()
submit_registration()
send_notification()
```

必须支持幂等。

Key 可以由：

```text
execution_id
+
capability_id
+
operation
+
request_hash
```

构造。

重复执行：

```text
第一次：
CREATE

第二次：
返回已有结果
```

---

# 22. Lease / Fencing

多 Replica 环境：

```text
Agent A
Agent B
Agent C
```

同一个 Execution 必须保证：

> 同一时刻只有一个有效 Owner。

使用：

```text
Lease
+
CAS
+
Fencing Token
```

避免旧 Owner 在失去租约之后继续写入状态。

---

# 23. Multi-Replica

V3 支持：

```text
             Load Balancer
                    │
        ┌───────────┼───────────┐
        ↓           ↓           ↓
     Runtime A   Runtime B   Runtime C
        │           │           │
        └───────────┼───────────┘
                    ↓
               PostgreSQL
```

共享：

```text
Checkpoint
Lease
Idempotency
Execution Metadata
```

这样单实例失败后：

```text
Runtime A
   X
   ↓
Checkpoint
   ↓
Runtime B
   ↓
Recovery
```

---

# 24. Service 与 Agent 的关系

Service ≠ Agent。

例如：

```text
knowledge-service
```

可能只是：

```text
Tool + Remote
```

而：

```text
nl2sql-service
```

如果它自己执行：

```text
理解问题
 ↓
找表
 ↓
生成 SQL
 ↓
验证
 ↓
执行
 ↓
观察错误
 ↓
修复
 ↓
重新执行
```

则可以是：

```text
Agent + Remote
```

因此：

```text
                 Semantic
             ┌──────┴──────┐
            Tool          Agent
             │              │
             └──────┬───────┘
                    ↓
              Execution
                    │
        ┌───────────┼───────────┐
        ↓           ↓           ↓
    InProcess     Remote     Sandbox
```

---

# 25. Application 架构

Applications 是业务应用和平台宿主。

建议保持：

```text
applications/
├── agent_server
├── agent_federation
├── dialogue-framework
├── exhibition-agent
├── knowledge-service
├── nl2sql-service
└── kefu-service
```

但不能把：

```text
Application = Agent
```

作为架构规则。

Application 是部署单元。

Capability 是能力单元。

Agent 是决策语义。

Execution Boundary 是运行边界。

四者必须分离。

---

# 26. Package 与 Application 边界

保持：

```text
Application
      ↓
agent-runtime
      ↓
agent-core
```

以及：

```text
shared-schemas
```

用于跨进程契约。

禁止：

```text
Application A
      ↓
Application B
```

直接 Python import。

跨进程：

```text
HTTP / RPC
+
shared-schemas
```

---

# 27. 推荐目录结构

> **注意：以下为目标态示意，非当前仓库状态，也不是改造指令。** 当前仓库结构见 `ARCHITECTURE.md` §6。此处仅表达 Capability / Execution Boundary / Scheduler 三层在目录中应如何分离的意图。

```text
packages/
├── agent-core/
│   ├── capability/
│   ├── agent/
│   ├── workflow/
│   ├── state/
│   └── schemas/
│
├── agent-runtime/
│   ├── execution/
│   ├── scheduler/
│   ├── executor/
│   │   ├── inprocess/
│   │   ├── remote/
│   │   └── sandbox/
│   ├── reliability/
│   ├── context/
│   └── governance/
│
└── shared-schemas/

applications/
├── agent_server/
├── agent_federation/
├── exhibition-agent/
├── knowledge-service/
├── nl2sql-service/
└── kefu-service/
```

---

# 28. Capability Registry

Registry 只负责：

```text
发现
注册
元数据
版本
Schema
Policy
```

不负责决定：

```text
部署在哪里
是否必须 Remote
```

例如：

```text
CapabilityRegistry
       ↓
knowledge.search
       │
       ├── kind = Tool
       ├── version = v1
       ├── execution = Remote
       ├── timeout = 10s
       └── concurrency = 20
```

Execution Router 再根据 metadata 选择 Executor。

---

# 29. 动态 Agent

平台支持动态创建 Agent。

例如 Supervisor：

```text
主任务
 ↓
分析
 ↓
发现需要招商分析
 ↓
动态创建
招商分析 Agent
 ↓
执行
 ↓
返回结果
 ↓
销毁 Agent Run
```

注意：

> Agent Definition 可以复用。

但：

> Agent Run 是一次执行实例。

因此动态 Agent 不一定需要永久存在。

---

# 30. State Ownership

Multi-Agent 场景下避免所有 Agent 共享一个巨大 State。

推荐：

```text
Supervisor State
    │
    ├── task
    ├── plan
    ├── progress
    └── child executions
              │
              ↓
       Child Agent State
          │
          ├── local plan
          ├── tool results
          └── observations
```

Supervisor 不直接修改 Child Agent 内部 State。

通过：

```text
AgentResult
Event
Artifact
```

交换结果。

---

# 31. 并发模型

平台支持三种并发：

## Execution 并发

```text
Execution A
Execution B
Execution C
```

## Capability 并发

一个 Execution 内：

```text
Tool A ─┐
Tool B ─┼── parallel
Tool C ─┘
```

## Multi-Agent 并发

```text
Supervisor
   │
   ├── Agent A
   ├── Agent B
   └── Agent C
```

三种并发必须分别治理。

---

# 32. 并发限制层级

建议：

```text
Global
  ↓
Tenant
  ↓
Agent
  ↓
Execution
  ↓
Capability
  ↓
Provider
```

例如：

```text
Global = 500
Tenant A = 100
Agent = 20
Execution = 5
Capability = 10
LLM Provider = 50
```

这样一个 Agent 无法因为自身异常把整个系统拖垮。

---

# 33. 资源隔离原则

判断是否 Remote，不依据：

```text
"它是不是 Agent"
```

而依据：

```text
资源
故障
扩缩容
依赖
安全
发布
```

推荐：

| 场景       | Boundary  |
| -------- | --------- |
| 轻量 Tool  | InProcess |
| 简单 Agent | InProcess |
| 纯 I/O    | InProcess |
| CPU 密集   | Remote    |
| GPU      | Remote    |
| 大模型      | Remote    |
| 重型 RAG   | Remote    |
| 独立扩缩容    | Remote    |
| 强故障隔离    | Remote    |
| 用户代码     | Sandbox   |

---

# 34. 会展业务映射

最终可以形成：

```text
                    会展智能体
                         │
                  Supervisor Agent
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
   知识 Agent         招商 Agent        数据分析 Agent
       │                 │                 │
       ↓                 ↓                 ↓
 Knowledge Tool      招商 Tools        NL2SQL Agent
       │                                   │
       ↓                                   ↓
knowledge-service                  nl2sql-service
```

但底层统一由：

```text
Agent Runtime
```

负责：

```text
Execution
State
Checkpoint
Scheduling
Concurrency
Retry
Idempotency
Lease
Fencing
Observability
Tenant/Auth
```

---

# 35. 一个完整请求的执行过程

用户：

> "分析今年上海展会招商情况，并给出重点行业。"

执行：

```text
1. API Gateway
       ↓
2. 创建 Agent Run
       ↓
3. Supervisor Agent
       ↓
4. Planning
       ↓
5. Capability Selection
       ↓
6. Scheduler Admission
       ↓
7. Execution
       ↓
8. Tool / Agent
       ↓
9. Observation
       ↓
10. State Update
       ↓
11. Checkpoint
       ↓
12. Next Decision
       ↓
13. Continue
       ↓
14. Terminal
```

其中某个 Capability 如果：

```text
CPU/GPU/重依赖
```

则：

```text
RemoteExecutor
```

如果只是：

```text
简单查询
```

则：

```text
InProcessExecutor
```

对 Agent 本身没有区别。

---

# 36. 故障恢复

假设：

```text
Execution
  1
  2
  3
  4 ← crash
```

Checkpoint：

```text
after step 3
```

实例崩溃：

```text
Runtime A
   X
```

Lease 超时：

```text
Runtime B
   ↓
Acquire Lease
   ↓
Fencing
   ↓
Load Checkpoint
   ↓
Resume
```

重新执行第 4 步。

因此：

> Durable Execution 是"重新驱动"，不是恢复原来的 Python 调用栈。

---

# 37. 失败控制

统一：

```text
Timeout
   ↓
Retry
   ↓
Circuit Breaker
   ↓
Fallback / Replan
   ↓
Terminal Failure
```

错误分为：

### 参数错误

可以：

```text
LLM correction
```

### Capability 暂时失败

可以：

```text
Retry
```

### 持续失败

```text
Circuit Breaker
```

### 数据不足

```text
Replan
```

### 不可恢复错误

```text
FAILED
```

---

# 38. Observability

每次 Capability Execution 都应关联：

```text
trace_id
execution_id
agent_run_id
capability_id
tenant_id
provider
latency
tokens
cost
status
retry_count
queue_time
execution_time
```

特别需要区分：

```text
Queue Time
Execution Time
LLM Time
Tool Time
DB Time
```

这样才能判断高延迟到底来自：

```text
Scheduler
Runtime
Network
LLM
Database
Capability
```

---

# 39. 成本治理

Agent 平台不能只控制并发，还需要控制预算。

Execution：

```text
budget
├── token
├── time
├── tool_calls
├── child_agents
└── cost
```

例如：

```text
max_tokens = 100k
max_tool_calls = 50
max_child_agents = 5
deadline = 120s
```

超过预算：

```text
STOP
```

---

# 40. 安全边界

所有 Capability Execution 必须经过：

```text
Authentication
       ↓
Authorization
       ↓
Tenant Isolation
       ↓
Capability Policy
       ↓
Execution
```

Agent 不应该绕过 Runtime 直接访问：

```text
DB
Redis
内部服务
```

业务 Agent：

```text
Agent
 ↓
Domain API / Capability
 ↓
Data
```

而不是：

```text
Agent
 ↓
Database
```

---

# 41. 数据访问原则

Agent 永远不直接操作业务数据库。

```text
Agent
   ↓
Capability / Domain API
   ↓
Domain Service
   ↓
Database
```

Domain API 负责：

```text
权限
租户
字段脱敏
审计
业务规则
数据定义
```

这样可以避免 Agent 绕过企业数据治理。

---

# 42. V3 与 V2 的关系

V2：

> Reliable Agent Execution

核心：

```text
Checkpoint
Lease
Fencing
Idempotency
Retry
Recovery
HA
```

V2 生产级验收约束（C1–C5，定义见 `complete-agent-runtime-architecture.md` §20）：

- **C1** — 跨副本状态变更必须原子 CAS
- **C2** — PG = source of truth，LISTEN/NOTIFY = 唤醒信号
- **C3** — admission 是行级事实 + TTL，不是全局 counter
- **C4** — 生产模式 fail fast，不自动 fallback InMemory
- **C5** — 测试必须覆盖四组（单元语义 / 并发 CAS / kill-pod resume / NOTIFY 丢失恢复）

> **V3 继承 C1–C5，不替代。** V3 在 C1–C5 之上增加平台化能力，不放松任何 V2 约束。

V3：

> Execution Platformization

在 V2 基础上增加：

```text
Capability
Registry
Execution Boundary
Scheduler
Concurrency
Backpressure
Resource Governance
Unified Context
Observability
```

即：

```text
V2
Reliable Execution
        ↓
V3
Platformized Execution
```

---

# 43. V3 不应该做什么

V3 不应该为了"平台化"而：

### 不应该强制所有 Capability Remote

否则：

```text
简单 Tool
 ↓
HTTP
 ↓
Serialization
 ↓
Network
 ↓
Service
```

增加大量复杂度。

---

### 不应该强制所有 Agent 独立部署

Agent 是语义模型。

部署是运行时选择。

---

### 不应该把 asyncio Task 当 Agent

```text
asyncio.create_task()
```

只是执行机制。

---

### 不应该把 Service 当 Agent

Service 是 Deployment Boundary。

---

### 不应该为了 exactly-once 引入复杂分布式事务

优先：

```text
At-least-once
+
Idempotency
+
Checkpoint
+
Fencing
```

---

# 44. 推荐的最终架构

最终平台形成：

```text
                         User
                           │
                           ↓
                     API Gateway
                           │
                           ↓
                 ┌──────────────────┐
                 │   Agent Runtime   │
                 │                  │
                 │  Agent Decision  │
                 │        │         │
                 │  Capability      │
                 │        │         │
                 │    Scheduler     │
                 │        │         │
                 │    Execution     │
                 │        │         │
                 │   Reliability   │
                 └────────┬─────────┘
                          │
                    Execution Router
                          │
              ┌───────────┼───────────┐
              ↓           ↓           ↓
          InProcess     Remote      Sandbox
              │           │           │
              ↓           ↓           ↓
          Light Tool   Domain      User Code
          Light Agent  Service
                       Model
                       RAG
                       NL2SQL
```

---

# 45. 核心架构结论

整个 V3 最终可以浓缩成五句话：

### 第一

> **Agent 是决策语义，不是部署单元。**

### 第二

> **Tool / Agent / Workflow 是 Capability 的不同执行语义。**

### 第三

> **InProcess / Remote / Sandbox 是 Execution Boundary。**

### 第四

> **Scheduler 决定并发、背压和资源分配。**

### 第五

> **Runtime 负责把 Agent 的动态决策转化成可靠、可恢复、可治理的 Execution。**

最终形成：

```text
             Capability
        ┌──────┼──────┐
       Tool   Agent  Workflow
        └──────┼──────┘
               ↓
          Scheduler
               ↓
           Execution
               ↓
     ┌─────────┼─────────┐
     ↓         ↓         ↓
 InProcess   Remote   Sandbox
     │         │         │
     └─────────┼─────────┘
               ↓
          Reliability
               ↓
      State / Checkpoint
      Lease / Fencing
      Retry / Idempotency
```

**这就是 V3 应该稳定下来的核心架构边界。**
