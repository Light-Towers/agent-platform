# V3 最终架构总纲：Execution Platform（不是 Agent Framework）

> 状态：**规划文档（架构总纲，不实现代码）**。
> 定位：`docs/plans/v3-roadmap-breakdown.md`（V3-1~V3-7 能力域 + 依赖图）的**上层抽象与补充**，不覆盖它。
> 对应：Issue #11 Part B/C；本文件把 7 域重新组织成 **8 层架构**，并补齐 Issue #11 未充分展开的 4 个语义层。
> 分支：`v3`；引用 HEAD `e0c5878`（当前 `85b4fcd`，已再前进 5 commit，方向一致）。
> 日期：2026-09-22。

---

## 0. 与现有文档的关系

| 文档 | 角色 | 本文件关系 |
|------|------|-----------|
| `v3-roadmap-breakdown.md` | V3-1~V3-7 能力域 + 依赖图 + Part C 红线 | **保留**，本文件是其上层抽象 |
| `plan-f-single-runtime-multi-planner.md` | Plan-F 单 Runtime + 多 Planner 演进 | **保留**，本文件是 Plan-F 之后的平台化目标 |
| `docs/analysis/2026-09-21/00-inventory.md` 等 | 架构盘点 + 剩余债务评估 | **保留**，本文件据此判断"已成熟 vs 未闭环" |
| Issue #11 | v2→v3 母路线 | **保留**，本文件精化其优先级并补 4 个语义层 |

**不冲突原则**：本文件的 8 层架构与 Issue #11 的 7 域是**同一批能力的两种切法**——7 域按"做什么"，8 层按"平台分层"。任一 milestone 都能同时打上两层标签。

---

## 1. 总体判断：V3 已到了"换目标"的时候

### 1.1 已基本成形（Agent Runtime 前半段）

| 能力 | 状态 | 证据 |
|------|------|------|
| Planner 抽象（Deterministic / Workflow / Dynamic Graph / Agentic） | ✅ | 已接入统一 Planner |
| SkillRegistry + Function/Agent/Remote/Workflow/MCP Skill + Discovery + 权限 + Composition | ✅ | `packages/agent-runtime/skills/` |
| Admission | ✅ | `packages/agent-runtime/admission/` |
| PG Checkpoint + Lease/Ownership + stale recovery | ✅ | v2 已完成 |
| ContextManager + Budget + Compaction | ✅ | `packages/agent-runtime/planner/context_manager/` |
| Middleware（timeout/retry/rate_limit/audit） | ✅ | `packages/agent-runtime/` |
| Agentic Runtime Bridge | ✅ | `planner/agentic_bridge/` |
| Trajectory + PG Trajectory + Replay | ✅ | 已有 |
| OTel + EventBus | ✅ | `agent-core/events/` + `agent-runtime/otel/` |
| MCP / Remote Skill | ✅ | `skills/mcp/` |

**结论**：继续堆 Agent 功能（更多 Planner / Tool / MCP）收益已不高。

### 1.2 还没闭环（Execution Platform 后半段）

```text
Execution Semantics → External Task → Scheduler → Control Plane → State Governance → Tenant/Scale
```

**核心叙事转换**：

```text
v2 = Reliable Agent Execution Runtime
v3 = Execution Platform  （Execution 本身成为平台级一等资源，像 Pod / Job / Order / Transaction）
```

所有 Agent（Deterministic / Workflow / Graph / Agentic）本质上都只是**生成并驱动 Execution 的不同方式**。

---

## 2. 最终架构：8 层

```text
                         ┌─────────────────────────┐
                         │      Control Plane       │  ⑥ inspect/replay/ops
                         └────────────┬────────────┘
                                      │
Request
  │
  ▼
Gateway / Auth / Tenant
  │
  ▼
Admission / Quota / Priority
  │
  ▼
Mode Selector
  │
  ├── Deterministic
  ├── Workflow
  ├── Dynamic Graph
  └── Agentic
          │
          ▼
        Planner
          │
          ▼
      Policy / Governance
          │
          ▼
      Execution Object
          │
    ┌─────┼──────────────────────────┐
    │     │                          │
    ▼     ▼                          ▼
  Queue  Runtime                  State
    │     │                          │
    │     ├── Skill                  ├── Checkpoint
    │     ├── Middleware             ├── Schema version
    │     ├── Lease/Fencing          ├── Compaction
    │     ├── Retry                  ├── Retention
    │     └── Budget                 └── Large context
    │
    ├──────────────┐
    ▼              ▼
External Task    Side Effect
    │              │
 receipt/status   Effect Contract
 callback         idempotency
 timeout          receipt
 cancel           compensation
    │              │
    └──────┬───────┘
           ▼
       Event / Trace
           │
       Trajectory
           │
       Replay / Audit
```

| 层 | 名称 | 职责 | 对应 Issue #11 域 | 当前状态 |
|---|------|------|----------------|---------|
| ① | **Execution Kernel** | Execution Identity / Lease / Generation / Checkpoint / State / Recovery | V3-1 + V3-6 部分 | ⚠️ Lease/Checkpoint 已有，generation 未严格 |
| ② | **Execution Semantics** | Effect Contract / Idempotency / Receipt / External Task / Human Task / Cancellation / Retry / Compensation | V3-2 + V3-3 + 补充 | ❌ Effect Contract 未形成；External Task 未独立 |
| ③ | **Execution Scheduler** | Queue / Dispatch / Priority / Fairness / Capacity / Backpressure / Retry / Reaper / Reschedule | V3-4 | ❌ 仅有 Admission，无真正调度 |
| ④ | **Agent Runtime** | Planner / Workflow / Dynamic Graph / Agentic / Skill / Context / Policy / Budget | （Plan-F 已完成） | ✅ 已成熟 |
| ⑤ | **Execution Observability** | Trace / Metrics / Events / Trajectory / Audit / Cost / Timeline | V3-5 部分 | ✅ 底座已有，缺 execution 级 HA metrics |
| ⑥ | **Control Plane** | Inspect / Pause / Resume / Cancel / Retry / Replay / Recover / Debug | V3-5 部分 | ⚠️ 底层数据已有，控制面未形成 |
| ⑦ | **Governance Plane** | Tenant / Identity / Permission / Quota / Skill Version / Policy / Approval / Retention / Audit | V3-7 + 补充 | ⚠️ 有接口非平台级隔离；Skill 版本/生命周期缺 |
| ⑧ | **Storage / Scale Plane** | State Schema / Migration / Compaction / Retention / Large Payload / Partition / Archive / Sharding | V3-6 本体 | ❌ Schema version/migration/compaction/large payload 均缺 |

---

## 3. 十大缺口（按维度，含严重级别）

> 严重级别：**High** = 阻塞生产闭环 / **Medium** = 影响平台感 / **Low** = 后期容量触发。

### 缺口 1：严格 Fencing Generation（V3-1） — **High**

**当前事实**：PG checkpoint 用 `version = len(completed)` 防 stale write；`execution_leases` 只有 `owner/expires_at`，无 generation 列。

**当前部分能力**：能防 checkpoint stale write，但不能防"旧 owner 改 execution status / external task receipt / side effect receipt / scheduler ownership"。

**目标架构**：

```text
Execution
├── ownership { owner, generation = 7 }
└── state     { checkpoint_version = 31 → 32 }
```

所有 durable write 带 `WHERE generation = ?`：checkpoint / execution status / external task receipt / side effect receipt / scheduler ownership。

**修复建议**：`execution_leases` 加 `generation` 列（Migration Layer A，仅 ALTER TABLE）；fencing 边界覆盖 5 类 durable write。**不重写 v2 checkpoint 数据模型**（Part C 红线）。

### 缺口 2：Effect Contract（V3-2） — **High**

**当前事实**：有 `SideEffectStore` / `IdempotencyStore` / `effect_key` / `idempotency_key`。

**当前部分能力**：能记录"这个 effect 已执行"，但平台不知道"这个 effect 应该如何 delivery/retry/recover"。

**目标架构**：

```text
EffectContract
├── effect_key
├── delivery_semantics   (at-most-once / at-least-once / effectively-once)
├── idempotency_strategy (business-key / ...)
├── receipt_strategy     (external-id / ...)
├── retry_policy         (safe / unsafe / query-first)
└── failure_recovery     (query-before-retry / manual / compensation)
```

**修复建议**：`SideEffectStore ≠ Effect Contract`——前者是记录，后者是语义契约。Scheduler 据此做失败分类：safe retry / query status first / don't retry / manual recovery。**平台不承诺 effectively-once**，只在特定 idempotency/receipt 条件下实现业务语义。

### 缺口 3：External Task + Receipt（V3-3） — **High**

**当前事实**：代码树无独立 `ExternalTask` 持久化模型。Durable Execution 只覆盖"Agent crash → checkpoint → resume"，不覆盖"外部任务异步进行时 Agent 不应一直占 worker"。

**当前部分能力**：Checkpoint 能恢复 Agent 内部状态，但恢复时不知道外部任务实际状态，只能盲目重调 Tool。

**目标架构**：

```text
ExternalTask
├── state: PENDING → SUBMITTED → RUNNING → COMPLETED
│         异常: FAILED / TIMED_OUT / CANCELLED / UNKNOWN
├── external_task_id / submission_receipt / completion_receipt
├── provider / submitted_at / completed_at
└── crash recovery: load → query external system → determine actual state → continue
```

**修复建议**：新建 `ExternalTask` 独立持久化模型 + 状态机；覆盖支付/订单/消息投递/视频生成/文件处理/异步 SQL/数据导入/MCP 异步/Webhook。

### 缺口 4：Execution Scheduler（V3-4） — **High**

**当前事实**：链路是 `Admission → Planner → Execute`，无 Queue/Scheduler。

**当前部分能力**：Admission 回答"现在允不允许开始"，不回答"哪个 Execution 由哪个 Worker 在什么时候执行"。

**目标架构**：

```text
Request → Admission → Execution Created → Queue → Scheduler → Worker → Lease/Fencing → Run
```

Scheduler 至少考虑：priority / fairness / tenant quota / worker capacity / backpressure / queue latency / retry / stuck / reschedule / reaper。

**修复建议**：拆 V3-4 为 V3-4A Dispatch + V3-4B Recovery/Retry。**不自建 K8s Scheduler**（Part C 红线），用 PostgreSQL/Redis 做队列 + 自研轻量调度策略。

### 缺口 5：Durable Execution Status State Machine — **High**

**当前事实**：状态机不完整，只有 RUNNING/SUCCESS/FAILED 骨架。

**当前部分能力**：能跑能完成，但无法表达 long-running / awaitable 语义。

**目标架构**：补 `WAITING / PAUSED / WAITING_EXTERNAL / WAITING_HUMAN / CANCEL_REQUESTED / CANCELLED`。

**修复建议**：与缺口 3 合并抽象为 **Awaitable Task**（External / Human / Timer / Callback 四子类），会展"合同变更需人工确认"场景即 `WAITING_HUMAN → 审批 → RESUME`。

### 缺口 6：State Schema Version / Migration（V3-6 Layer B） — **Medium**

**当前事实**：PG checkpoint 是 `completed JSONB / version / resumable`，无 `state_schema_version`。

**当前部分能力**：假设 checkpoint 永远兼容当前代码。

**目标架构**：`state_schema_version = 3` + migration 链 `v1 → v2 → v3`，旧 checkpoint 自动迁移而非炸代码。

**修复建议**：V3-6 拆 Layer A（DB schema migration，轻量，V3-1 前置）+ Layer B（State schema migration，V3-6 本体）。不要为"加一列 generation"就搭完整 State Schema Migration Framework。

### 缺口 7：Large Payload Externalization（V3-6 Layer B） — **Medium**

**当前事实**：工具返回 50MB JSON 直接塞 checkpoint JSONB。

**当前部分能力**：能存能恢复，但 PG JSONB 不适合大对象，影响 compaction/retention/查询性能。

**目标架构**：

```text
large result → object/blob store → checkpoint 只保存 reference
```

**修复建议**：checkpoint 拆 `current snapshot / event-history / large payload references / external artifacts / compressed historical state`。**不自建对象存储**（Part C 红线），用现有 S3/MinIO/本地 blob。

### 缺口 8：Control Plane（V3-5B） — **Medium**

**当前事实**：Trajectory / Checkpoint / Events / OTel / Audit / Lease / SideEffects 数据已存在，但未形成"人可运营 Execution"的控制面。

**当前部分能力**：能 Replay，能看 Trajectory，但不能执行 pause/resume/cancel/retry/requeue/recover/inspect/terminate。

**目标架构**：Execution Control Plane 暴露 execution_id / tenant / request / planner / mode / status / current step / owner / generation / attempt / queue time / run time / checkpoint / external tasks / side effects / errors / cost / tokens / trace，并支持上述操作。

**修复建议**：底层基础已具备（Trajectory/Replay），这一步是"把数据变成可操作的面"，不是从零建。

### 缺口 9：Replay Forensic / Reproducibility — **Medium**

**当前事实**：`TrajectoryRecord` 记录 execution_id / plan / steps / result / error / latency / tokens / cost / snapshot。

**当前部分能力**：能检测"Step 3 发生 divergence"，但不能回答"是模型变/prompt 变/Skill schema 变/数据变/外部 API 结果变/Policy 变"。

**目标架构**：Trajectory 额外记录 `model / model_version / provider / prompt_version / skill_version / input_schema_version / tool_schema / planner_version / policy_version / important external inputs / external task receipt / effect receipt`。

**修复建议**：从"行为漂移检测"升级到"Execution forensic / reproducibility"。与缺口 10（Skill version）联动。

### 缺口 10：Skill Version / Lifecycle / Compatibility — **Medium**（Issue #11 补充）

**当前事实**：SkillRegistry 有 name/permissions/composition，无 version/compatibility/lifecycle/deprecation。

**当前部分能力**：Skill 热更新会破坏 Runtime Replay / Checkpoint Recovery / Workflow。

**目标架构**：

```text
Skill
├── name / version / input_schema / output_schema
├── permissions / dependencies / health / owner
└── compatibility / lifecycle / deprecation
```

**修复建议**：`venue.schedule.query v1 → v2` 升级时，旧 Execution 继续用 v1，新 Execution 用 v2。Skill 是一等公民但"Skill 生命周期"必须成为平台能力。

---

## 4. 补充语义层（Issue #11 未充分展开，建议纳入 V3）

| # | 语义层 | 归属 | 优先级 |
|---|--------|------|--------|
| 补-1 | **Awaitable Task**（External / Human / Timer / Callback 统一抽象） | 层 ② | P1 |
| 补-2 | **Skill Version / Lifecycle / Compatibility** | 层 ⑦ | P1 |
| 补-3 | **Cost / Resource Governance 多层预算**（Request → Execution → Skill → Tenant → Platform） | 层 ⑦ | P1 |
| 补-4 | **Replay Forensic**（model/prompt/skill/policy version 全记录） | 层 ⑤+⑥ | P1 |

---

## 5. 优先级排序（P0/P1/P2）

| 优先级 | 功能 | 缺口 # | 对应 Issue #11 |
|--------|------|--------|---------------|
| **P0** | strict fencing generation | 1 | V3-1 |
| **P0** | Effect Contract | 2 | V3-2 |
| **P0** | ExternalTask + receipt | 3 | V3-3 |
| **P0** | Scheduler / dispatch | 4 | V3-4A |
| **P0** | durable execution status state machine（含 Awaitable） | 5 | V3-3 + 补-1 |
| **P1** | State schema version / migration | 6 | V3-6 Layer B |
| **P1** | large payload externalization | 7 | V3-6 Layer B |
| **P1** | Control Plane | 8 | V3-5B |
| **P1** | Replay Forensic | 9 | V3-5 + 补-4 |
| **P1** | Skill version / lifecycle | 10 | 补-2 |
| **P1** | durable cancel / pause / resume | 5 子项 | V3-3 |
| **P1** | tenant quota / cost governance | — | V3-7 + 补-3 |
| **P1** | human task / approval | — | 补-1 |
| **P2** | state retention / archival | — | V3-6 Layer B |
| **P2** | partition / sharding | — | V3-7（capacity-triggered） |
| **P2** | multi-region | — | 暂不提前做 |

**依赖图**（与 `v3-roadmap-breakdown.md` 一致，不串行）：

```text
V3-6A (DB migration) → V3-1 (fencing) → V3-2 (Effect Contract) → V3-3 (External Task) → V3-4A (Dispatch) → V3-4B (Recovery) → V3-5B (Control Plane)
V3-5A (Metrics) 横切前置
V3-6B (State schema/compaction/retention) 横向支撑 V3-2/V3-3/V3-5
V3-7 capacity-triggered，无固定顺序
```

---

## 6. 不建议继续加的内容（红线扩展）

> 与 `v3-roadmap-breakdown.md` Part C 一致并扩展。

```text
❌ 2PC / Raft / Paxos
❌ Runtime 自己做分布式事务
❌ Runtime 强行 Exactly-Once（平台不承诺，只提供实现手段）
❌ 自建完整 MQ
❌ 自建完整对象存储
❌ 自建完整 Kubernetes Scheduler
❌ 自建完整 IAM
❌ 把 RAG / SQL / 知识库全塞进 Runtime（已有 knowledge-service / nl2sql-service 独立服务）
❌ 继续堆更多 Planner / Agent / Tool / MCP（Agent Runtime 前半段已成熟，收益已低）
```

**正确方向**：

```text
Runtime = execution kernel
                │
   ┌────────────┼────────────┐
   ▼            ▼            ▼
PostgreSQL    Redis       Object Store
   │            │            │
state/effect  cache     large payload
```

以及 `External Scheduler / Queue → Execution Runtime`，而不是 Runtime 自己成为所有基础设施的替代品。

---

## 7. 验收标准（方案级，非代码级）

| 维度 | 验收 |
|------|------|
| Execution 一等对象 | `execution_id / tenant / state / owner / generation / attempt / queue / priority / budget / checkpoint / effects / external_tasks / events / trace / trajectory / status / created_at / updated_at` 全部持久化且可查询 |
| Fencing 完整 | 5 类 durable write（checkpoint / status / external receipt / effect receipt / scheduler ownership）均带 `WHERE generation = ?`，旧 owner 写任一类均被拒 |
| Effect Contract | `EffectContract` 6 字段齐全，Scheduler 据此做失败分类（safe retry / query first / don't retry / manual） |
| External Task | `ExternalTask` 独立持久化 + 状态机 + crash recovery（load → query external → determine state → continue） |
| Scheduler | Queue + Dispatch + Priority + Fairness + per-tenant concurrency + Reaper，非 FIFO |
| Awaitable | External / Human / Timer / Callback 四子类统一抽象，`WAITING_HUMAN → 审批 → RESUME` 可跑通 |
| Control Plane | pause/resume/cancel/retry/requeue/recover/inspect/terminate/replay 全部可操作 |
| Replay Forensic | Trajectory 含 model/prompt/skill/policy version，能回答"为什么这次和上次不一样" |
| Skill Lifecycle | `v1 → v2` 升级时旧 Execution 继续用 v1、新 Execution 用 v2 |
| State Governance | `state_schema_version` + migration 链 + large payload externalization + compaction |
| 不越红线 | 未引入 2PC/Raft/自建 MQ/自建对象存储/自建 K8s Scheduler/自建 IAM；RAG/SQL 仍在独立服务 |

---

## 8. 后续推进方式

1. **本文件作为 V3 最终架构总纲**，后续每个 P0/P1 milestone 单独写 plan（如 `plan-v3-1-strict-fencing-generation.md`），不在此文件展开实现细节。
2. **不重写 `v3-roadmap-breakdown.md`**——7 域划分与 8 层架构是同一批能力的两种切法，并存。
3. **P0 五项先做**：fencing generation → Effect Contract → ExternalTask → Scheduler Dispatch → status state machine。这五项闭环后 V3 才算"Execution Platform"而非"Agent Framework"。
4. **每个 milestone 遵守 AGENTS.md 红线**：先方案（目标/影响面/迁移策略/验收）后代码；不删用例凑绿；不重写 v2 已验证的 HA 不变量。
5. **容量触发的项（partition/sharding/multi-region）不提前做**，等容量信号出现再启动。

---

## 9. 我的判断（与用户方案对照）

**完全一致**。用户方案是 `v3-roadmap-breakdown.md` 的精化 + 补充 + 重新抽象，不是冲突：

- **精化**：P0/P1/P2 三级排序比原 roadmap 的依赖图更直白，便于排期。
- **补充**：补-1 Awaitable Task / 补-2 Skill Lifecycle / 补-3 Cost Governance / 补-4 Replay Forensic 是 Issue #11 原始 7 项未充分展开的，确实是"Execution Platform 真正做大后必须出现的"。
- **重新抽象**：8 层架构比 7 域更清晰——把 Agent Runtime 独立成一层（已成熟，不再加），把 Governance 和 Storage-Scale 分开（前者偏策略后者偏容量），把 Control Plane 独立（平台感的核心）。
- **红线扩展**：与 Part C 一致并补"不再堆 Agent 功能"，方向正确。

**无须修改的点**：用户方案中"HEAD e0c5878"是 5 commit 之前的快照，当前 `85b4fcd` 已再前进，但方向一致，不影响方案。
