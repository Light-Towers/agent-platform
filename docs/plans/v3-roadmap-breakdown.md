# v3 Roadmap：Reliable Execution Runtime → Execution Platform

> 状态：**规划文档（v3 规划评审稿）**。不实现任何代码。
> 对应：Issue #11 Part B（V3-1 ~ V3-7）+ Part C（明确不做）。
> v2 已 freeze（`v2.0.0`）；本规划**不破坏 v2 已验证的 HA 不变量**。

---

## 0. 总原则（最重要）

> **v3 不再解决 "Agent 如何可靠执行"（这是 v2 的问题），而是解决
> "可靠的 Agent Execution 如何成为一个可编排、可恢复、可观测、可扩展的 Execution Platform"。**

```text
v2 = Reliable Execution Runtime
v3 = Execution Platform
```

**Part C 红线（贯穿所有 V3 设计评审，不默认做）：**
- Exactly-Once Execution 的绝对承诺
- 2PC / 分布式事务作为默认执行机制
- 为理论上的网络分区构造复杂 consensus
- 在 Runtime 层强行保证第三方 API 的 exactly-once
- 为 strict fencing epoch 重构已经稳定的 v2 checkpoint 数据模型（只加列，不重写）

---

## 1. 七个能力域（保留 Issue #11 划分，不再拆成十几块）

| 域 | 内容 | 复用 v2 现状 |
|---|---|---|
| V3-1 | strict fencing epoch / generation | `PgExecutionOwnershipStore`（加 generation 列） |
| V3-2 | business side-effect consistency（Effect Contract） | `PgSideEffectStore` / `PgIdempotencyStore` |
| V3-3 | external durable execution | 无（全新 ExternalTask） |
| V3-4 | production scheduler | 无（ownership 只管"谁能执行"） |
| V3-5 | observability / control plane | otel 埋点（需补 execution 级 HA metrics） |
| V3-6 | execution state governance | `PgCheckpointStore`（需 version/migration/compaction） |
| V3-7 | multi-tenant / high-concurrency / DB scale | 无（capacity-triggered） |

> 关键：每个域是"能力域 + 若干独立 milestone"，**不是做完一个再做一个的大 Epic**。

---

## 2. 依赖关系：依赖图 + Phase（不是串行链）

**拒绝**串行顺序：
```text
❌ V3-6 → V3-1 → V3-2 → V3-3 → V3-4 → V3-5 → V3-7
```

**采用依赖图**：

```text
                         ┌──────────────┐
                         │ V3-6A        │
                         │ DB migration │   (仅 ALTER TABLE 级别的 schema migration)
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │ V3-1         │
                         │ fencing epoch│
                         └──────┬───────┘
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
          ┌──────────────┐              ┌──────────────┐
          │ V3-2         │              │ V3-5A        │   ← V3-5 横切前置，非后置
          │ Effect       │              │ Metrics      │
          │ Contract     │              │              │
          └──────┬───────┘              └──────────────┘
                 │
                 ▼
          ┌──────────────┐
          │ V3-3         │
          │ External     │
          │ Durable Task │
          └──────┬───────┘
                 │
                 ▼
          ┌──────────────┐
          │ V3-4A        │   Dispatch（谁应该执行）
          └──────┬───────┘
                 ▼
          ┌──────────────┐
          │ V3-4B        │   Recovery/Retry（失败后怎么办）
          └──────┬───────┘
                 ▼
          ┌──────────────┐
          │ V3-5B        │   Control Plane
          └──────────────┘

          V3-6B（State schema/compaction/retention）
                ├── 横向支撑 V3-2
                ├── 横向支撑 V3-3
                └── 横向支撑 V3-5

          V3-7（capacity-triggered，无固定开发顺序）
```

---

## 3. V3-6 拆成两个迁移层（避免过度设计）

| 层 | 名称 | 范围 | 归属 |
|---|---|---|---|
| **Migration Layer A** | DB schema migration | `ALTER TABLE ... ADD generation` | V3-1 的必要基础，**轻量** |
| **Migration Layer B** | Execution State Schema Migration | checkpoint v1→v2→v3、compaction、retention、large context | V3-6 本体 |

> 不要为"加一列 generation"就先搭完整的 State Schema Migration Framework。
> V3-1 只需要 Migration Layer A（DB migration 纪律），Migration Layer B 才是 V3-6 的事。

---

## 4. V3-1：strict fencing epoch / generation

### 4.1 两个数字必须解耦

```text
generation = ownership epoch     → 谁在持有 lease（owner 的代数）
version    = checkpoint/state version → 状态推进了几次

Execution
│
├── ownership
│     └── generation = 7
│
└── state
      ├── checkpoint version = 31
      └── checkpoint version = 32
```

避免 `generation / version / attempt / lease / sequence` 几个数字互相混淆。

### 4.2 fencing 边界：不只是 checkpoint

old generation 的**任何需要证明 execution ownership 的 durable write 都必须拒绝**：

```text
checkpoint
execution status transition
external task completion
side-effect receipt mutation
scheduler ownership mutation
```

否则会出：`checkpoint 被 fence 住了，但 execution status 还能被旧 owner 改` —— strict fencing 不完整。

### 4.3 设计要点

- takeover 后 generation 单调递增
- checkpoint/status/receipt 写入带 `WHERE generation = current`
- old owner 用旧 generation 写 → 拒绝
- generation 与 checkpoint version 完全解耦

---

## 5. V3-2：Effect Contract（风险最高模块，语义必须收紧）

### 5.1 明确平台不承诺

**❌ 错误表述**：`Tool 声明 delivery=exactly-once-effectively → 平台自动保证 effectively-once`

**为什么错**：平台 `IdempotencyRegistry` 只能解决"平台自己知道某 effect_key 已执行/确认"，
**不能凭空知道第三方到底有没有成功执行**。

```text
POST /payment
  1. POST 成功
  2. payment server 已扣款
  3. agent 在收到 response 前 crash
  4. agent recovery
  5. agent 不知道 POST 是否成功
```

### 5.2 DeliverySemantics（严谨三分）

```text
DeliverySemantics
    ├── at-most-once
    ├── at-least-once
    └── effectively-once
```

> **effectively-once 是一个"在特定 idempotency / receipt 条件下实现的业务语义"，
> 不是 Runtime 的绝对保证。**

### 5.3 核心对象：Effect Contract（不是裸 DeliverySemantics）

```text
Effect Contract
    ├── effect_key
    ├── delivery_semantics
    ├── idempotency_strategy
    ├── receipt_strategy
    ├── retry_policy
    └── failure_recovery
```

示例：
```text
Tool: create_order
  effect_key:        order_id
  delivery:          effectively-once
  idempotency:       business-key
  receipt:           external-order-id
  retry:             safe
```

这样平台才知道"这个副作用为什么可以 retry"。

---

## 6. V3-3：External Durable Execution

### 6.1 不是所有外部 API 都能"receipt 恢复"

必须引入 **External Task Capability**：

| 外部系统 | 能力 |
|---|---|
| synchronous API | retry |
| idempotent API | retry safely |
| async job API | query status |
| callback API | callback receipt |
| resumable job | resume |
| non-idempotent API | manual recovery |

> 不能简单 `receipt 不存在 → retry`，否则会重复业务副作用。

### 6.2 核心：External Task State Machine

```text
PENDING
   ↓
SUBMITTED
   ↓
RUNNING
   ↓
COMPLETED
   │
   ├── FAILED
   ├── TIMED_OUT
   └── CANCELLED
```

并持久化：
```text
submission receipt
completion receipt
external task id
```

### 6.3 crash recovery 语义

```text
agent crash
  ↓
load ExternalTask
  ↓
inspect receipt
  ↓
query external system
  ↓
determine state
  ↓
continue
```

**而不是** `没有 checkpoint → 重跑 Tool`。这才是 v3 真正的 Durable Execution。

---

## 7. V3-4：Production Scheduler（拆成两阶段）

### V3-4A：Execution Dispatch
> 核心问题：**谁应该执行？**
```text
queue
capacity
priority
backpressure
```

### V3-4B：Execution Recovery Policy
> 核心问题：**执行失败之后怎么办？**
```text
retry
stuck detection
reaper
rescheduler
circuit breaker
```

### 7.1 Retry 必须绑定 Effect Contract（V3-2/V3-4 最大耦合点）

**❌ 不能**：
```text
Scheduler → failed → retry
```

**✅ 应该**：
```text
failed
  ↓
classify failure
  ↓
is retryable?
  ↓
does task have safe effect semantics?   ← 读 V3-2 Effect Contract
  ↓
retry
```

否则 `HTTP POST timeout → Scheduler retry → POST again` 会业务执行 2 次。

> V3-4 **依赖 V3-2 的 Effect Contract**，但**不需要等 V3-2 全部完成**（可并行迭代）。

---

## 8. V3-5：Observability / Control Plane（横切前置）

### 8.1 V3-5 必须从 V3 第一阶段开始，是横切能力

```text
             ┌─ V3-1 fencing
             │
             ├─ V3-2 side effect
             │
Observability├─ V3-3 external task
             │
             └─ V3-4 scheduler
```

否则会出现："最后才加 metrics" → instrumentation 再做一遍。

### 8.2 分两层

**V3-5A：Operational Metrics（先有）**
```text
execution_count
execution_duration
attempt_count
takeover_count
takeover_latency
checkpoint_lag
stuck_count
recovery_count
```

> 现状：v2 otel 已有埋点，但无 execution 级 HA metrics（takeover/checkpoint_lag/recovery_count
> 均为空）—— V3-5A 是**横切新增**，从 Phase 0 开始埋。

**V3-5B：Control Plane（后做）**
```text
execution timeline
execution inspection
attempt history
owner history
checkpoint inspection
replay/debug
```

> **Replay/Debug UI 不应该是 V3-5 的前置条件**，它很容易变成一个独立产品，降级为后置能力。

---

## 9. V3-6：Execution State Governance（验收语义要精确）

### 9.1 区分两种 equivalence

| 类型 | 定义 |
|---|---|
| **State equivalence** | compaction 前 state == compaction 后 state |
| **Replay equivalence** | same checkpoint + same deterministic inputs → same logical state |

### 9.2 对 LLM Agent 要谨慎

LLM output 未必 deterministic，不能写"replay 一定得到完全相同结果"。严谨定义：

> **在记录了必要 external inputs / tool receipts / execution decisions 的条件下，
> replay 能恢复到等价的 durable execution state。**

---

## 10. V3-7：Multi-tenant / Scale（capacity-triggered，无固定顺序）

**不是 Feature Epic，而是 SLO/容量触发型工程**：

```text
connection pool saturation → Pool tuning
tenant hotspot            → Partition
execution count/table size → Archival
single PG bottleneck      → Sharding / HA strategy
```

> 只有真实容量/SLO 触发才启动，不提前做数据库大工程（贯彻 Issue #11 "当并发规模上来后"）。

---

## 11. 建议启动顺序：5 个 Phase（不是 7 个）

| Phase | 内容 | 目标 |
|---|---|---|
| **Phase 0：Foundation** | V3-6A DB migration + V3-1 fencing epoch + V3-5A 基础 metrics | 把 v2 correctness 再提升一层 |
| **Phase 1：Effect Semantics** | V3-2 Effect Contract + Idempotency Registry + Receipt + Delivery Semantics | 解决"Agent 执行"与"业务副作用"的边界 |
| **Phase 2：External Durable Execution** | V3-3 ExternalTask + submission/completion receipt + callback + timeout + cancellation | Durable Execution 从 PG 内部扩展到外部世界 |
| **Phase 3：Production Scheduler** | V3-4A queue/capacity/priority/backpressure + V3-4B retry/stuck/reaper/rescheduler/circuit breaker | 从"能可靠执行"到"能生产级调度" |
| **Phase 4：Control Plane + State Governance** | V3-5A metrics + V3-5B control plane + V3-6B schema/compaction/retention/large context | 从"可靠 Runtime"到"可运营平台" |
| **Phase 5：Scale** | V3-7 | 仅容量/SLO 触发 |

---

## 12. 最易架构事故的三个点（评审重点）

1. **V3-2 Effect Contract**：平台绝不承诺"声明 effectively-once 就自动保证"；effectively-once 是条件性业务语义。
2. **V3-3 ExternalTask State Machine**：必须引入 state machine + receipt，否则 crash recovery 退化为"重跑 Tool"导致副作用重复。
3. **V3-4 Retry 与副作用语义绑定**：retry 必须消费 V3-2 的 Effect Contract，不能单独设计。

---

## 13. 本文档与 v2 代码现状一致性核对

| 断言 | 现状 |
|---|---|
| v2 有 PG 后端四件套可复用 | ✅ `PgCheckpointStore` / `PgIdempotencyStore` / `PgExecutionOwnershipStore` / `PgSideEffectStore` 均存在 |
| v2 无 DeliverySemantics / EffectContract / ExternalTask / state machine | ✅ 全代码库无匹配（纯 v3 新设计） |
| v2 otel 有埋点但无 execution 级 HA metrics | ✅ takeover/checkpoint_lag/recovery_count/attempt_count 均未实现 |
| v2 已 freeze，不重写 checkpoint 数据模型 | ✅ v2.0.0 tag；V3-1 只加列不重写 |

---

*规划文档，不实现代码。启动 v3 时以本文 + Issue #11 为母文档，每个 Phase 单独出 spec。*
