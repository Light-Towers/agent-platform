# 方案 P0-1（选 B）：ExecutionScheduler 扶正为真执行门控

> 来源：`docs/plans/arch-audit-2026-09-24.md` P0-1。审计给出 A/B/C 三选，产品拍板 **B**。
> 本方案满足 AGENTS.md「先方案后编码」红线：含目标 / 影响面 / 迁移策略 / 验收标准。
> 基线：`scheduler_enabled` 默认 `False`（`config.py:143`），故本改动为 opt-in，关闭时零行为变化。

## 1. 目标（对齐 P0-1 四缺陷）

把 `/query` 上的 Scheduler 从「旁路记账 + 记错账」升级为真正的执行门控，逐项消除：

| # | P0-1 缺陷 | B 方案目标 |
|---|-----------|-----------|
| ① | `max_concurrent`/`max_concurrent_per_tenant` 完全失效 | 认领槽位失败即 **HTTP 503**（`Retry-After`）拒绝，超并发不再放行 |
| ② | `dispatch_next()` 无参 → 错标队首他人任务、从不调 `mark_running` | 新增**请求驱动认领** `try_start(execution_id)`：只认领 `execution_id=本请求` 的行，原子 `QUEUED→RUNNING`；`/query` 路径不再调 `dispatch_next()` |
| ③ | 行滞留 `DISPATCHED` → Reaper 伪造 `FAILED` 污染下游 | 认领直接进 `RUNNING`，正常结束在 `finally` 落终态；不再产生「无人认领的 DISPATCHED」 |
| ④ | `complete(request_id)` 缺 `status` → `TypeError` 被 `logger.debug` 吞 | 修正为 `complete(execution_id, COMPLETED/FAILED)`，失败走 `logger.warning` |

**保留不动**：`dispatch_next()`（无参、队首拉取）语义不变——它是 ControlPlane/retry 与后台 Worker 拉取模型的 API，多处单测依赖；本方案只新增 `try_start`，不改 `dispatch_next`。

## 2. 影响面

- `packages/agent-runtime/agent_runtime/execution_scheduler.py`
  - `SchedulerStore` 契约新增抽象方法 `try_start(execution_id, config) -> ExecutionRequest | None`。
  - `InMemorySchedulerStore` / `PgSchedulerStore` 各实现一个；`ExecutionScheduler` 门面加 `try_start(execution_id)`。
  - `SchedulerStore` 仅两个子类（均在本文件内）→ 新增抽象方法不破坏外部实现（已 `git grep` 确认）。
- `applications/agent_server/api/query_router.py`（`/query`）
  - **删除**生成器内 `dispatch_next()` 块（`:260-267`）。
  - **新增**在 `return StreamingResponse(_stream())` 之前认领：`try_start` 失败 → `cancel` 掉自己 QUEUED 行 + `raise HTTPException(503, "SCHEDULER_SLOTS_EXHAUSTED")`。
  - **修正** `finally` 中 `complete(request_id, COMPLETED/FAILED)` + 移除已失效的 P0-1 注释。
- 认领点选在生成器**之前**（handler body 末尾）的意义：此时 admission reject(`:97`)、coordinator reject(`:130`)、cache-hit return(`:149`) 均已提前发生 → 这些早退路径尚未占用**槽位**（`try_start` 之前，QUEUED 不占 slot），无槽位泄漏；认领成功后唯一的出口是进入 `_stream()`，其 `finally` 必然 `complete` 释放。
  - **backpressure 记账补充修正**：`submit` 在 handler 开头就写入 `QUEUED` 行，而 `queue_depth()`（=`count_queued`）是 `submit` 的 `QueueFull` 判据。cache-hit 早退不占槽位但会遗留 `QUEUED` 行 → 永久虚增 `queue_depth`、误导 backpressure（属缺陷①「记错账」的镜像）。故在 cache-hit return 前 `cancel(request_id)` 撤销自己那行（`scheduler_enqueued` 守卫，向后兼容）。admission/coordinator reject 为异常拒绝路径，遗留 QUEUED 行由 Reaper 兜底，不在本次收敛范围。

## 3. 迁移策略

- **向后兼容**：`scheduler_enabled=False` 时 `scheduler is None`，所有新分支跳过，与现状逐字节一致。
- **并发正确性**：`PgSchedulerStore.try_start` 在事务内先取 `pg_advisory_xact_lock`（key = 常量，跨实例串行化「数槽 + 认领」的临界区），再 `FOR UPDATE` 锁定目标行确认仍为 `QUEUED`，然后全局/per-tenant 计数门控，最后 `UPDATE ... WHERE status='QUEUED'`。比现有 `dequeue` 的 `SKIP LOCKED` 更严格（避免边界超额）。
- **InMemory 原子性**：`try_start` 从读取到改写之间无 `await`，单事件循环内天然原子。
- 无需 DDL 变更（`execution_queue` 表结构不变；`status`/`worker_id`/`dispatched_at` 均已存在）。
- 灰度：默认关；开启后 503 仅在该租户/全局槽位打满时触发，与 Admission/Coordinator 的容量门控叠加（三层各自独立）。

## 4. 验收标准（可测）

1. `InMemorySchedulerStore.try_start`：
   - 空闲时认领指定 `execution_id` → 返回该 req、状态 `RUNNING`、`worker_id` 非空；
   - 全局 `running_total >= max_concurrent` → 返回 `None` 且不改状态；
   - 单租户 `>= max_concurrent_per_tenant`（全局未满）→ 返回 `None`；
   - 目标行非 `QUEUED`（已认领/终态/不存在）→ 返回 `None`。
2. `/query`（`scheduler_enabled=True`，mock store）：超并发时认领失败 → HTTP 503；未超则正常执行且 `complete` 以终态收尾。
3. 现有 `dispatch_next()`/control_plane/execution_recovery 单测**全部保持通过**（未改其语义）。
4. `make lint` / `ruff check` 对改动文件全绿；`pytest packages/agent-runtime/tests -q` 全绿。
5. `git grep "dispatch_next()" -- query_router.py` 无命中；`grep "complete(request_id)"`（单参）无命中。

## 5. 风险与回退

- 风险：真实生产 PG 下 `try_start` 的 advisory lock 增加认领临界区串行度——仅在 `scheduler_enabled` 且打满边缘显著，规模内可接受。
- 回退：本方案为纯增量 + 接线，回退 = 关 `scheduler_enabled`（默认即关）或 revert 本组提交；不影响其他模块。
