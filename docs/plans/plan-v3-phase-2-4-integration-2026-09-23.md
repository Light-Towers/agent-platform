# V3 Phase 2-4：Integration & Completion

> 状态：**方案文档（v2，已补 6 项不变量，待确认后施工）**。
> 前置：V3 Phase 1（ExecutionBoundary）已完成；V3 架构基线见 `docs/architecture/agent-execution-platform.md`。
> 日期：2026-09-23（v2 修订：补 C6 跨实例并发 / Callback 幂等 / Reaper lease-based / Session-AgentRun-Execution 三层 / 状态转换矩阵 / CostRecord 可追溯）。
> 分支：`v3`。

---

## 0. 盘点结论：P0 五项已实现，缺的是集成

经代码盘点（2026-09-23），V3 P0 五项缺口**均已作为独立模块实现**，且有单元测试覆盖。当前真正的缺口是：

> **V3 模块存在于 `packages/agent-runtime/`，但未接入 `applications/agent_server/` 主执行链路。**

### 已实现模块清单

| P0/P1 | 缺口 # | 模块 | 文件 | 测试 | PG 后端 | 接入 app |
|-------|--------|------|------|------|---------|----------|
| P0 | 1 | Fencing Generation | `planner/durability_pg.py` + `execution_state_pg.py` | ✅ | ✅ | ✅ |
| P0 | 2 | Effect Contract | `effect_contract.py` | ✅ | N/A | ⚠️ 字段存在，未全量声明 |
| P0 | 3 | AwaitableTask（External/Human/Timer/Callback） | `awaitable_task.py` | ✅ | ❌ InMemory | ❌ |
| P0 | 3 | ExecutionStatus State Machine | `execution_status.py` | ✅ | ✅ | ⚠️ 存在，未接入主流程 |
| P0 | 4 | ExecutionScheduler | `execution_scheduler.py` | ✅ | ✅ | ❌ |
| P0 | 5 | （含在 3 内） | — | — | — | — | — |
| P1 | 6 | State Schema Migration | `state_migration.py` | ❌ | ✅ | ✅ checkpoint 读写 |
| P1 | 7 | Payload Externalization | `payload_externalization.py` | ✅ | N/A | ⚠️ ContextAssembler |
| P1 | 8 | Control Plane | `control_plane.py` | ✅ | Mixed | ❌ |
| P1 | 9 | Forensic | `forensic.py` | ✅ | N/A | ⚠️ trajectory 字段，未填充 |
| P1 | 10 | Skill Lifecycle | `skill_lifecycle.py` | ✅ | N/A | ⚠️ 字段存在，未强制 |
| P1 | 补-3 | Cost Governance | `cost_governance.py` | ✅ | ❌ InMemory | ❌ |
| P1 | 补-1 | Human Task | `human_task.py` | ✅ | ❌ InMemory | ❌ |

### 真正的缺口（6 项）

1. **ExecutionContext 缺字段**：缺 `tenant_id` / `principal` / `authorization_context` / `session_id` / `trace_id` / `agent_run_id` / `cancellation_token`（架构基线 §10 要求）
2. **Scheduler 未接入**：`ExecutionScheduler` 存在但 `applications/agent_server/` 无 import，请求仍走 `Admission → Planner → Execute`，未过 Queue/Dispatch
3. **AwaitableTask 无 PG 后端**：`PgAwaitableTaskStore` 不存在，生产环境无法持久化外部任务状态
4. **Cost Governance 无 PG 后端**：`PgBudgetStore` 不存在，且未接入执行路径
5. **Control Plane 无 API**：`ControlPlane` 操作（inspect/pause/resume/cancel/retry/terminate）未暴露 HTTP 端点
6. **Forensic 未填充**：`TrajectoryRecord.forensic` 字段存在但执行路径未写入 `ForensicContext`

### 次要缺口（3 项，不阻塞）

7. **Scheduler Reaper**：`list_overdue` 接口已预留，Reaper 协程未实现
8. **State Migration 无测试**：`state_migration.py` 无 dedicated test
9. **Skill Lifecycle 未强制**：`Skill.lifecycle` 字段存在但 registry 未拒绝 RETIRED / 未警告 DEPRECATED

---

## 0.5 Session / AgentRun / Execution 三层 ID 关系

ExecutionContext 新增 `session_id` / `agent_run_id` / `execution_id` 三个 ID，必须明确三者层级关系：

```text
Session（对话 / 业务会话上下文）
  │
  ├── AgentRun-1（一次 Agent 目标执行）
  │      ├── Execution-1（Runtime 可恢复、可调度的执行单元）
  │      ├── Execution-2
  │      └── Execution-3
  │
  └── AgentRun-2
         ├── Execution-4
         └── Execution-5
```

| 层级 | >语义 | 生命周期 | 持久化 |
|------|------|---------|--------|
| **Session** | 对话 / 业务会话上下文（用户一次连续交互） | 跨多次 AgentRun | 对话历史（thread_id） |
| **AgentRun** | 一次 Agent 目标执行（goal + context + constraints） | 跨多次 Execution（retry / sub-agent） | checkpoint + trajectory |
| **Execution** | Runtime 可恢复、可调度的执行单元 | 一次调度生命周期 | scheduler queue + status + lease |

**约束**：
- `session_id` 可跨 Execution 复用（同一对话内多次请求）
- `agent_run_id` 可跨 Execution 复用（retry 产生新 Execution 但同 AgentRun）
- `execution_id` 全局唯一，不可复用
- checkpoint 按 `execution_id` 存储，对话历史按 `session_id`（thread_id）存储

这与架构基线 §4（Agent Definition / Agent Run / Execution）一致：

```text
Agent Definition（静态蓝图）
        ↓
     Agent Run（一次具体工作）
        ↓
     Execution（Runtime 调度单元）
        ↓
     Capability Execution（Step）
```

---

## 1. Phase 2：ExecutionContext 富化 + Scheduler 接入

### 1.1 目标

把 `ExecutionScheduler` 接入 `agent_server` 主请求路径，使请求从 `Admission → Planner → Execute` 升级为 `Admission → Scheduler Queue → Dispatch → Planner → Execute`。同时富化 `ExecutionContext` 补齐架构基线 §10 字段。

### 1.2 ExecutionContext 富化

**改动文件**：`packages/agent-runtime/agent_runtime/planner/protocol.py`

**新增字段**（`ExecutionContext` dataclass）：

```python
# V3 §10：企业级平台必需的执行上下文字段
agent_run_id: str | None = None        # Agent Run 实例 ID（与 execution_id 解耦）
session_id: str | None = None          # 会话线程 ID（对话历史持久化）
tenant_id: str | None = None           # 租户 ID（多租户隔离）
principal: str | None = None           # 调用主体（API key / service account）
authorization_context: dict[str, Any] = field(default_factory=dict)  # 权限上下文（roles/scopes）
trace_id: str | None = None            # 分布式追踪 ID（OTel）
cancellation_token: Any = None         # 取消令牌（asyncio.Event 或外部信号）
```

**向后兼容**：全部带默认值，现有调用方不受影响。

**`ExecutionIdentity` 扩展**：新增 `tenant_id` 字段（默认 `"default"`），与 `workspace_id` / `user_id` 并列。

### 1.3 Scheduler 接入

**改动文件**：`applications/agent_server/main.py`（lifespan 装配）

**装配顺序**：

```text
lifespan:
  ...
  scheduler_store = PgSchedulerStore(pool)  # 或 InMemory（DATABASE_URL 未配置时）
  scheduler = ExecutionScheduler(scheduler_store, config=SchedulerConfig(
      max_concurrent=settings.max_concurrent_executions,
      max_concurrent_per_tenant=settings.max_concurrent_per_tenant,
      queue_capacity=settings.scheduler_queue_capacity,
  ))
  app.state.scheduler = scheduler
  app.state.status_store = PgExecutionStatusStore(pool)
```

**请求路径改动**（`applications/agent_server/api/` 路由层）：

```text
POST /api/chat:
  1. Admission（现有，不删）
  2. scheduler.submit(ExecutionRequest(...))  → 入队
  3. scheduler.dispatch_next()  → 取出并 mark_running
  4. 创建 ExecutionContext（富化字段）
  5. status_store.save(RUNNING)
  6. Planner.execute(plan, runtime, ctx)
  7. status_store.save(SUCCEEDED / FAILED)
  8. scheduler.complete(execution_id)
```

**关键约束**：
- Admission 不删除（回答"允不允许"），Scheduler 叠加（回答"什么时候执行"）
- `DATABASE_URL` 未配置时退化为 InMemory（零依赖冒烟不破坏）
- 现有 SSE 流式出口不变，Scheduler 在入队后立即 dispatch（不引入可观测延迟）
- **Scheduler Queue 是 Execution 的持久化调度队列，不承担通用消息总线职责**——当前瓶颈是执行所有权、并发控制、恢复和 backpressure，不是消息吞吐

### 1.4 C6 Scheduler 跨实例并发不变量

> **多实例部署下，并发限制必须是全局的，不是 per-process 的。**

```text
agent_server-1 / agent_server-2 / agent_server-3
同时服务 tenant A

max_concurrent_per_tenant = 10

❌ 错误：每个实例各持 asyncio.Semaphore(10) → 实际并发 = 30
✅ 正确：并发限制由 PG 原子 claim 保证 → 实际并发 <= 10
```

**不变量 C6**：

```text
对于同一 Execution：
  至多一个 Scheduler Worker 持有 RUNNING slot

对于同一 tenant：
  全局并发数 <= max_concurrent_per_tenant（跨所有实例）

对于系统：
  全局并发数 <= max_concurrent（跨所有实例）
```

**实现保证**：

- `PgSchedulerStore.dispatch_next()` 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 原子认领——多实例并发 dispatch 不会认领同一行
- 并发计数由 PG 行级事实维护（`running_count = COUNT(WHERE status = 'running' AND tenant_id = ?)`），不是 Python 内存 counter
- `InMemorySchedulerStore` 仅用于单实例 / 测试，不满足 C6（文档标注此限制）

**与 V2 C1–C5 的关系**：C6 是 C1（CAS）在 Scheduler 层的延伸——Lease / Fencing / Checkpoint 保证"同一 Execution 至多一个 owner"，C6 保证"同一 tenant 至多 N 个 Execution 同时 RUNNING"。两者共用 PG 原子操作底座，不各自重新设计一套。

### 1.4 影响面

| 文件 | 改动类型 |
|------|---------|
| `packages/agent-runtime/agent_runtime/planner/protocol.py` | 加字段（ExecutionContext + ExecutionIdentity） |
| `applications/agent_server/main.py` | lifespan 装配 scheduler + status_store |
| `applications/agent_server/api/*.py` | 请求路径加 scheduler submit/dispatch |
| `applications/agent_server/config.py` | 新增 scheduler 配置项 |

### 1.5 验收标准

- `ExecutionContext` 含 §10 全部字段，默认值不破坏现有测试
- `ExecutionScheduler` 在请求路径中可观测（queue_depth > 0 时 backpressure）
- **C6**：`PgSchedulerStore` 用 `FOR UPDATE SKIP LOCKED` 原子认领，多实例并发不超限
- `ExecutionStatusStore` 记录 PENDING → RUNNING → SUCCEEDED/FAILED 完整生命周期
- 零依赖冒烟（`DATABASE_URL=` uvicorn）仍通过
- 现有 434 + 523 测试全绿

---

## 2. Phase 3：PG 持久化 + Reaper + AwaitableTask 接入

### 2.1 目标

补齐 `PgAwaitableTaskStore` 和 `PgBudgetStore`，实现 Scheduler Reaper，将 AwaitableTask 接入执行路径以支持外部异步任务。

### 2.2 PgAwaitableTaskStore

**新增文件**：`packages/agent-runtime/agent_runtime/awaitable_task_pg.py`

**DB 迁移**（`packages/agent-runtime/agent_runtime/db.py`）：

```sql
CREATE TABLE IF NOT EXISTS awaitable_tasks (
    task_id          TEXT PRIMARY KEY,
    execution_id     TEXT NOT NULL,
    step_id          TEXT,
    kind             TEXT NOT NULL,          -- external / human / timer / callback
    state            TEXT NOT NULL,          -- pending / submitted / running / completed / ...
    provider         TEXT,
    provider_task_id TEXT,
    submission_receipt JSONB,
    completion_receipt JSONB,
    resume_payload   JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata         JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_awaitable_execution ON awaitable_tasks(execution_id);
CREATE INDEX IF NOT EXISTS idx_awaitable_state ON awaitable_tasks(state);
```

**实现**：`load` / `save`（带状态转换校验） / `list_by_execution` / `list_by_state`，与 `InMemoryAwaitableTaskStore` 同接口。

### 2.3 PgBudgetStore

**新增文件**：`packages/agent-runtime/agent_runtime/cost_governance_pg.py`

**DB 迁移**：

```sql
CREATE TABLE IF NOT EXISTS budget_usage (
    tenant_id   TEXT NOT NULL,
    dimension   TEXT NOT NULL,              -- requests / tokens / cost / duration
    bucket_index BIGINT NOT NULL,           -- 固定窗口分桶
    used        DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, dimension, bucket_index)
);

CREATE TABLE IF NOT EXISTS budget_limits (
    tenant_id     TEXT NOT NULL,
    dimension     TEXT NOT NULL,
    limit_value   DOUBLE PRECISION NOT NULL,
    window_seconds INTEGER NOT NULL DEFAULT 3600,
    PRIMARY KEY (tenant_id, dimension)
);
```

### 2.4 Scheduler Reaper（Lease-based，非 wall-clock timeout）

**改动文件**：`packages/agent-runtime/agent_runtime/execution_scheduler.py`

> **核心约束：Reaper 只能回收"已失去 owner / lease 已失效"的执行，不能仅依据 wall-clock timeout 判定执行已经终止。**

**问题场景（必须避免）**：

```text
Worker A 正在执行 Execution #123
    ↓
Reaper 判断 timeout（wall-clock）
    ↓
标记 #123 = FAILED + 释放 slot
    ↓
Worker B 拿到新 Execution，复用 slot
    ↓
Worker A 实际还在跑 #123（产生副作用）
```

结果：状态已 FAILED，但实际执行仍存在——slot 被双重占用。

**正确设计**：

```text
Reaper 周期扫描
    ↓
list_overdue()  →  返回 lease 已过期的执行（不是 wall-clock 超时）
    ↓
对每个 lease-expired 执行：
    1. 确认 lease 已失效（expires_at < now）—— 证明原 owner 已无权写
    2. generation fencing：用新 generation 写 FAILED（旧 owner 的写会被拒）
    3. 释放 slot
    4. 原 owner 的 ownership_lost 检测（§HA A 侧）会协作式中止
```

```python
class SchedulerReaper:
    """回收 lease 已失效的执行：标记 FAILED + 释放 slot。

    只回收 lease 已过期的执行（expires_at < now），不依据 wall-clock timeout。
    lease 过期 = 原 owner 已无权写（generation fencing 保证），可安全回收。
    """

    def __init__(
        self,
        scheduler: ExecutionScheduler,
        ownership_store: ExecutionOwnershipStore,
        interval_s: float = 30.0,
    ):
        self._scheduler = scheduler
        self._ownership = ownership_store
        self._interval_s = interval_s
        self._stopped = False

    async def run(self):
        while not self._stopped:
            # list_overdue 返回 lease 已过期的执行（非 wall-clock 超时）
            overdue = await self._scheduler.list_overdue()
            for req in overdue:
                # 确认 lease 确实已失效（双重检查，防 TOCTOU）
                owner = await self._ownership.get_owner(req.execution_id)
                if owner is not None and not owner.is_expired:
                    continue  # lease 仍有效，跳过（可能刚被续租）
                # generation fencing：用新 generation 写 FAILED
                await self._scheduler.complete(
                    req.execution_id,
                    status="failed",
                    reason="lease_expired",
                )
            await asyncio.sleep(self._interval_s)
```

**与 V2 Lease/Fencing 的关系**：Reaper 不重新设计恢复语义，复用 V2 已有的 lease 过期 + generation fencing + ownership_lost 检测。Reaper 只是 Scheduler 层的"lease 过期清扫器"，与 Checkpoint Recovery（v2 已有）是同一套 lease 语义的两个消费者。

**接入**：`agent_server` lifespan 启动 Reaper 后台协程，shutdown 时取消。

### 2.5 AwaitableTask 接入执行路径

**场景**：当 Skill 声明 `EffectContract(receipt_strategy=EXTERNAL_ID)` 且外部系统返回异步 task_id 时，执行路径应：

1. 创建 `AwaitableTask(EXTERNAL)`，状态 `SUBMITTED`
2. `ExecutionStatus` 转 `WAITING_EXTERNAL`（释放 Worker slot）
3. 外部回调 / 轮询 → `AwaitableTask` 转 `COMPLETED` + `resume_payload`
4. `ExecutionStatus` 转 `RUNNING`，Scheduler 重新 dispatch

**改动**：在 `PlannerRuntime.delegate()` 中，当 Skill 返回值含 `__awaitable__` 标记时自动创建 AwaitableTask 并暂停执行。这是增量改动，不影响同步 Skill 路径。

### 2.5.1 AwaitableTask Callback 幂等不变量

> **同一个 callback 重复到达，不能重复 resume Execution。**

外部系统回调可能重复发送（至少一次投递语义）。平台必须保证：

```text
callback 第 1 次 → AwaitableTask: COMPLETED → Execution: RUNNING
callback 第 2 次 → AwaitableTask: COMPLETED（幂等，不重复 resume）
```

**实现保证**：

```text
AwaitableTask completion = idempotent state transition

回调处理：
  1. load(task_id)
  2. 若 state 已是 COMPLETED → 直接返回（幂等，不重复 resume）
  3. 若 state 是 SUBMITTED/RUNNING → CAS 转 COMPLETED（带 generation fencing）
  4. CAS 成功 → resume Execution（RUNNING）
  5. CAS 失败（被其他 callback 抢先）→ 返回（幂等）
```

**幂等键**：`(task_id, provider_task_id, callback_event_id)`——同一外部任务的同一事件只处理一次。

**与 V2 Idempotency 的关系**：复用 V2 已有的 `IdempotencyStore` + `effect_key` 机制。AwaitableTask 的 completion 本身就是一个 side effect，其 `EffectContract` 为：

```python
EffectContract(
    effect_key=f"awaitable_complete:{task_id}",
    delivery_semantics=DeliverySemantics.AT_LEAST_ONCE,
    idempotency_strategy=IdempotencyStrategy.PLATFORM_KEY,
    receipt_strategy=ReceiptStrategy.EXTERNAL_ID,
    retry_policy=RetryPolicy.SAFE,
    failure_recovery=FailureRecovery.RETRY_SAFE,
)
```

**crash 恢复场景**：

```text
平台收到 callback
  ↓
写 COMPLETED
  ↓
进程 crash（resume 未执行）
  ↓
恢复
  ↓
load AwaitableTask → state = COMPLETED
  ↓
resume Execution（从 checkpoint 继续，注入 resume_payload）
```

恢复时检查 AwaitableTask 状态：COMPLETED 但 Execution 仍 WAITING_EXTERNAL → 执行 resume。这和 V2 Checkpoint Recovery 是同一套语义。

### 2.6 影响面

| 文件 | 改动类型 |
|------|---------|
| `packages/agent-runtime/agent_runtime/db.py` | 加 2 张表 DDL |
| `packages/agent-runtime/agent_runtime/awaitable_task_pg.py` | 新文件 |
| `packages/agent-runtime/agent_runtime/cost_governance_pg.py` | 新文件 |
| `packages/agent-runtime/agent_runtime/execution_scheduler.py` | 加 Reaper |
| `packages/agent-runtime/agent_runtime/planner/protocol.py` | delegate() 加 awaitable 检测 |
| `applications/agent_server/main.py` | lifespan 装配 PG stores + Reaper |

### 2.7 验收标准

- `PgAwaitableTaskStore` 通过 `InMemoryAwaitableTaskStore` 同套测试
- `PgBudgetStore` 通过 `InMemoryBudgetStore` 同套测试
- Reaper 只回收 lease 已失效的执行，不误杀活 Worker（lease 仍有效的跳过）
- 重复 callback 不重复 resume（AwaitableTask completion 幂等）
- AwaitableTask 路径：外部任务提交 → WAITING_EXTERNAL → 回调 → RUNNING 可跑通
- crash 恢复：COMPLETED 但 Execution 仍 WAITING_EXTERNAL → 自动 resume
- 现有测试全绿

---

## 3. Phase 4：Control Plane API + Cost Governance + Forensic 填充

### 3.1 目标

暴露 ControlPlane 操作为 HTTP API，接入 CostGovernance 到执行路径，填充 ForensicContext 到 Trajectory。

### 3.2 Control Plane API

**新增文件**：`applications/agent_server/api/control.py`

**端点**：

| Method | Path | 操作 | ControlPlane 方法 |
|--------|------|------|-------------------|
| GET | `/api/executions/{id}` | inspect | `control_plane.inspect(id)` |
| POST | `/api/executions/{id}/pause` | pause | `control_plane.pause(id)` |
| POST | `/api/executions/{id}/resume` | resume | `control_plane.resume(id)` |
| POST | `/api/executions/{id}/cancel` | cancel | `control_plane.cancel(id)` |
| POST | `/api/executions/{id}/retry` | retry | `control_plane.retry(id)` |
| POST | `/api/executions/{id}/terminate` | terminate | `control_plane.terminate(id)` |

**响应**：`ExecutionSnapshot` 序列化为 JSON（含 status / owner / generation / checkpoint_summary / external_tasks / side_effects）。

**权限**：admin 角色方可操作 pause/resume/cancel/retry/terminate；inspect 可放宽到 owner。

### 3.2.1 Control Plane 状态转换矩阵

> **Control Plane 是状态机的控制面，不是一堆 HTTP CRUD。**

每个操作只在合法的当前状态下允许，非法操作返回 409 Conflict：

| 当前状态 \ 操作 | inspect | pause | resume | cancel | retry | terminate |
|----------------|---------|-------|--------|--------|-------|-----------|
| PENDING | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| RUNNING | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| WAITING | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| WAITING_EXTERNAL | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| WAITING_HUMAN | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ |
| PAUSED | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ |
| CANCEL_REQUESTED | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| SUCCEEDED | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| FAILED | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| CANCELLED | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |

**语义说明**：
- `pause`：仅 RUNNING 可暂停（WAITING_* 不支持暂停，已有等待语义）
- `resume`：仅 PAUSED 可恢复（WAITING_* 的恢复由外部回调 / 人工审批驱动，不走 resume API）
- `cancel`：非终态、非 CANCEL_REQUESTED 均可取消（QUEUED 直接取消，RUNNING 标记 CANCEL_REQUESTED）
- `retry`：仅 FAILED / SUCCEEDED / CANCELLED 可 retry（创建新 Execution，attempt+1）
- `terminate`：非终态均可强制终止（直接 FAILED，不走 CANCEL_REQUESTED 协作式）

**实现**：复用 `execution_status.can_transition()` 做校验，非法转换返回 409 + `InvalidStatusTransition`。

### 3.3 Cost Governance 接入

**改动文件**：`applications/agent_server/main.py` + 请求路径

**接入点**：

```text
POST /api/chat:
  1. Admission
  2. cost_governance.check(tenant_id, REQUESTS)  → 超限抛 BudgetExceeded
  3. scheduler.submit(...)
  4. ... 执行 ...
  5. cost_governance.record(tenant_id, REQUESTS, 1)
  6. cost_governance.record(tenant_id, TOKENS, ctx.tokens_used)
  7. cost_governance.record(tenant_id, COST, ctx.cost_used)
```

**配置**：`BUDGET_LIMIT_REQUESTS` / `BUDGET_LIMIT_TOKENS` / `BUDGET_LIMIT_COST` 环境变量，按 tenant 设限。

### 3.3.1 CostRecord 可追溯性

> **Cost 不应只知道"tenant A 花了 $100"，应能追溯到哪个 Agent / Execution / Step / Model 花的。**

Agent 平台的真实成本结构：

```text
Execution
  ├── Planner LLM
  ├── Agent A
  │    ├── LLM
  │    ├── Tool
  │    └── LLM
  ├── Agent B
  │    ├── LLM
  │    └── Tool
  └── Retry
       └── LLM
```

**CostRecord schema（Phase 4 预留，不一定全实现）**：

```python
@dataclass(frozen=True)
class CostRecord:
    # 层级追溯链
    tenant_id: str
    session_id: str | None
    agent_run_id: str | None
    execution_id: str
    step_id: str | None

    # 计量明细
    model: str | None                    # 哪个模型
    skill_name: str | None               # 哪个 Skill
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # 费用
    estimated_cost: float = 0.0
    actual_cost: float = 0.0

    # 时间
    timestamp: float = field(default_factory=time.time)
```

**追溯查询**：

```text
tenant → session → agent_run → execution → step → model/skill
```

**Phase 4 范围**：
- 定义 `CostRecord` schema（`packages/agent-runtime/agent_runtime/cost_governance.py`）
- 在 `PlannerRuntime.delegate()` 的 `record_step()` 中填充 CostRecord（execution_id / step_id / tokens / cost 已有）
- PG 表 `cost_records` 建表（DDL 预留）
- **不实现**：聚合查询 API、多 tier 分层预算、按 model 成本分析 dashboard（等容量信号）

### 3.4 Forensic 填充

**改动文件**：`packages/agent-runtime/agent_runtime/planner/protocol.py`（`PlannerRuntime.delegate()`）

在 `record_step()` 时同步填充 `StepForensic`：

```python
step_forensic = StepForensic(
    skill_name=name,
    skill_version=skill.version,
    tool_name=name,
    tool_version=skill.version,
    model=ctx.metadata.get("model"),
    model_version=ctx.metadata.get("model_version"),
)
```

在 execution 完成时填充 `ForensicContext` 到 `TrajectoryRecord.forensic`。

### 3.5 Skill Lifecycle 强制

**改动文件**：`packages/agent-runtime/agent_runtime/skills/registry.py`

在 `register()` 时：
- `lifecycle == RETIRED` → 拒绝注册（`DuplicateSkillError` 改为 `SkillRetiredError`）
- `lifecycle == DEPRECATED` → logger.warning

在 `discover()` 时：
- `lifecycle == DEPRECATED` → 结果中标记 `metadata["deprecated"] = True`

### 3.6 State Migration 测试

**新增文件**：`packages/agent-runtime/tests/test_state_migration.py`

覆盖：
- `StateSchemaMigrator.register()` + `migrate()` 链式应用
- `needs_migration` 判定
- 跨版本迁移（v1 → v2 → v3）
- 无迁移函数时的 passthrough
- `StateMigrationError` 异常路径

### 3.7 影响面

| 文件 | 改动类型 |
|------|---------|
| `applications/agent_server/api/control.py` | 新文件（Control Plane API） |
| `applications/agent_server/main.py` | 装配 ControlPlane + CostGovernance |
| `applications/agent_server/api/*.py` | 请求路径加 cost check/record |
| `packages/agent-runtime/agent_runtime/planner/protocol.py` | delegate() 填充 forensic |
| `packages/agent-runtime/agent_runtime/skills/registry.py` | register/discover 强制 lifecycle |
| `packages/agent-runtime/tests/test_state_migration.py` | 新文件 |

### 3.8 验收标准

- Control Plane API 6 个端点可操作（inspect/pause/resume/cancel/retry/terminate）
- 状态转换矩阵校验：非法操作返回 409 + `InvalidStatusTransition`
- Cost Governance 超限时返回 429 + BudgetExceeded
- CostRecord schema 定义，可追溯到 execution_id / step_id / model
- ForensicContext 在 trajectory 中可查询
- RETIRED skill 注册被拒，DEPRECATED skill 注册有 warning
- `test_state_migration.py` 全绿
- 现有测试全绿

---

## 4. 依赖与顺序

```text
Phase 2 (ExecutionContext + Scheduler 接入)
    │
    ├── 独立：state_migration 测试（可并行）
    │
    ▼
Phase 3 (PG 持久化 + Reaper + AwaitableTask 接入)
    │
    ▼
Phase 4 (Control Plane API + Cost Governance + Forensic)
```

Phase 2 是 Phase 3 的前置（Scheduler 接入后才能加 Reaper 和 AwaitableTask）。
Phase 3 是 Phase 4 的前置（PG stores 就绪后 ControlPlane 才能在生产用）。

---

## 5. 红线遵守

- **不重写 v2 HA 不变量**：C1–C5 继承，不放松；新增 C6（Scheduler 跨实例并发不变量）
- **C6 实现**：PG 原子 claim（`FOR UPDATE SKIP LOCKED`），不用 `asyncio.Semaphore`（仅控单进程）
- **不删用例凑绿**：测试红时修产品代码到契约要求
- **agent-runtime 不反向 import 应用层**：所有新模块在 `packages/agent-runtime/`，app 只装配
- **Application 不互相 import**：Control Plane API 在 `agent_server`，不 import 其他 app
- **不自建 K8s / MQ / 对象存储**：Scheduler 用 PG 队列（Execution 调度队列，非通用消息总线），Payload 用现有 blob
- **Reaper lease-based**：只回收 lease 已失效的执行，不依据 wall-clock timeout
- **AwaitableTask callback 幂等**：复用 V2 IdempotencyStore，completion = idempotent state transition
- **Scheduler / Reaper / AwaitableTask 共享 V2 底座**：Lease + Fencing + Idempotency + Checkpoint，不各自重新设计一套
- **向后兼容**：所有新字段带默认值，`DATABASE_URL=` 零依赖冒烟不破坏

---

## 6. 不做（红线扩展）

```text
❌ 多 tier 分层预算（free/pro/enterprise）——等容量信号
❌ partition / sharding ——等容量信号
❌ multi-region ——暂不提前做
❌ 完整 IAM ——用现有 API key / service account
❌ 2PC / Raft / 分布式事务
❌ 重写 v2 checkpoint 数据模型
❌ Event Bus ——不自建通用事件总线
❌ Workflow DSL ——不自建工作流 DSL
❌ Service Mesh ——不引入服务网格
❌ 独立 Worker Platform ——Worker 即 agent_server 实例
❌ 独立 Metadata Platform ——metadata 在 PG
❌ 多级调度集群 ——单级 PG 队列足够
```

> **保持克制**：不再堆"企业级能力"。Runtime = execution kernel，不是微服务大杂烩。

---

## 7. 总验收（Phase 2-4 全部完成后）

| 维度 | 验收 |
|------|------|
| ExecutionContext | §10 全部字段就绪，含 tenant/principal/authz/trace/cancellation |
| Session/AgentRun/Execution | 三层 ID 关系明确，checkpoint 按 execution_id，对话历史按 session_id |
| Scheduler | 请求过 Queue → Dispatch → Execute，backpressure 可观测 |
| C6 跨实例并发 | PG 原子 claim 保证全局并发 <= max_concurrent（多实例验证） |
| AwaitableTask | PG 持久化，EXTERNAL 路径可跑通（提交 → WAITING → 回调 → RUNNING） |
| Callback 幂等 | 重复 callback 不重复 resume，completion = idempotent state transition |
| Reaper | lease-based 回收（非 wall-clock timeout），不与活 Worker 竞态 |
| Control Plane | 6 个 API 端点可操作，状态转换矩阵校验（非法操作返回 409） |
| Cost Governance | PG 持久化，超限返回 429，CostRecord 可追溯到 execution/step/model |
| Forensic | Trajectory 含 model/skill/policy version |
| Skill Lifecycle | RETIRED 拒绝注册，DEPRECATED 警告 |
| State Migration | 有 dedicated 测试 |
| 向后兼容 | 零依赖冒烟通过，现有测试全绿 |
| 不越红线 | 未引入 2PC/Raft/自建 MQ/自建 K8s/自建 IAM/Event Bus/Service Mesh/Workflow DSL |
| 共享 V2 底座 | Scheduler/Reaper/AwaitableTask 复用 Lease+Fencing+Idempotency+Checkpoint，不各自重新设计 |

---

## 8. 最终架构收敛

```text
                    ┌──────────────────────┐
                    │     API / Agent      │
                    └──────────┬───────────┘
                               │
                               ▼
                       ┌──────────────┐
                       │   Admission  │
                       │ 能不能执行？ │
                       └──────┬───────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │       Scheduler         │
                 │                         │
                 │ Queue (PG)              │
                 │ Concurrency (C6)        │
                 │ Backpressure            │
                 │ Lease / Claim (FOR UPDATE│
                 │   SKIP LOCKED)          │
                 └───────────┬─────────────┘
                             │
                             ▼
                 ┌─────────────────────────┐
                 │     Execution Runtime   │
                 │                         │
                 │ Planner                 │
                 │ Agent / Skill           │
                 │ Tool                    │
                 │ State / Checkpoint      │
                 └───────────┬─────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        AwaitableTask     ControlPlane    Cost
        (callback 幂等)   (状态矩阵)     (CostRecord)
              │
              ▼
       External System
              │
           callback
              │
              ▼
        Resume Execution


          ┌───────────────────────────┐
          │       PostgreSQL          │
          │                           │
          │ Execution State           │
          │ Checkpoint                │
          │ Scheduler Queue           │
          │ AwaitableTask             │
          │ Budget / CostRecord       │
          │ Lease / Fencing (C1-C6)   │
          └───────────────────────────┘
```

> **这就是 V3 Phase 2-4 完成后的 Agent Execution Platform Runtime。**
