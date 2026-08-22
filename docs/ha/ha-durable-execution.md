# Durable Execution / Execution HA 验证

> 核心命题：**一个 Agent Execution 在副本 A 执行到中途被杀死，副本 B 能接管，并从最近可靠
> checkpoint 继续，而不是重新执行已完成的副作用，也不是从头开始。**

验证方式：**故障注入 + 自动验收**（真 PostgreSQL，非 SQLite）。测试位于 `tests/ha/`。

---

## 一、验证的保证语义

不承诺 "Exactly Once Execution"（过度承诺）。严谨表述为：

| 维度 | 保证 |
|---|---|
| Execution | **at-least-once**（attempt 可能 >1） |
| Checkpoint | **durable**（每节点完成即落盘） |
| Ownership | **single active owner**（PG CAS + expires_at 自动过期） |
| Side effects | **idempotent / effectively-once**（唯一约束兜底） |
| 系统级结果 | **Effectively-once outcome** |

---

## 二、执行状态机（异常路径）

```
RUNNING
   │ replica crash / 网络分区（心跳无法到达 PG）
   ▼
LEASE EXPIRED   (expires_at 自动过期，非永久存在)
   │
   ▼
NEW OWNER       (PG CAS acquire：仅过期/无行/同 owner 时成功)
   │
   ▼
RESUME          (从 checkpoint.load 复用已完成节点，不重跑)
```

Split-brain 的 A 侧防护（本次补齐）：心跳带 `owner` 校验，被接管后返回 False →
置 `ownership_lost` → 执行循环逐层协作式中止，旧 owner 不再产生副作用。

---

## 三、测试矩阵（tests/ha/，10 个测试）

| 文件 | 场景 | 验证点 |
|---|---|---|
| `test_checkpoint_recovery.py` | 1：基础 checkpoint | checkpoint 真的落盘 S1/S2/S3，trajectory 连续 |
| `test_kill_after_checkpoint.py` | 2：kill after checkpoint | A 跑 S1/S2 被杀，B 从 checkpoint2 接管 S3/S4，S1/S2 **不重跑** |
| `test_kill_before_checkpoint.py` | 3：kill before checkpoint | S2 副作用已发生但 checkpoint 未写，B 重跑 S2 → **attempt≥2, effect=1** |
| `test_lease_expiration.py` | 4：lease 过期接管 | B 不能抢有效 lease；A lease 过期后 B 接管（单 owner） |
| `test_lease_contention.py` | 6：双恢复竞争 | B/C 同时 acquire，**恰一个成功一个被拒**（无最后写覆盖） |
| `test_idempotency_recovery.py` | 7：重复提交 | 同 execution_id 提交两次，副作用只发生一次 |
| `test_full_failover.py` | 组合灾难 | A kill → B 接管 → B 分区 → C 接管 → 完成，全 5 步副作用各 1 次 |
| `test_fault_injector.py` | FaultInjector | 注入器驱动 kill_after_checkpoint=step_2，A→B 接管 |
| `test_ha_invariants.py` | 验收 I1–I7 | 输出 HA RESULT: PASS 报告 |

---

## 四、验收 Invariant（I1–I7）

| # | Invariant | 实现保障 |
|---|---|---|
| I1 | 最终只能有一个完成结果 | checkpoint 唯一，completed 单调 |
| I2 | checkpoint 单调递增 | 每节点完成后才落盘，非降序 |
| I3 | 不跳过已确认 checkpoint | resume_from = latest_durable_checkpoint |
| I4 | 副作用不能重复 | side_effects 唯一约束（effect_key） |
| I5 | 同一时间最多一个 owner | PG CAS acquire（ON CONFLICT WHERE 过期/同 owner） |
| I6 | 失去 lease 后旧 owner 停止 | heartbeat owner 校验 → ownership_lost → 协作式中止 |
| I7 | 最终结果 deterministic | effectively-once → 最终状态唯一 |

---

## 五、运行方式

前置：真实 PostgreSQL（本机 5433 或 compose 起）：

```bash
# 方式一：本机已有 PG（默认连 postgresql://agent:agent_platform_dev@localhost:5433/agent_platform）
uv run pytest tests/ha -v

# 方式二：compose 双副本（生产级故障：docker kill agent-a）
docker compose -f docker-compose.ha.yml up --build -d
uv run pytest tests/ha -v
```

预期输出（`test_ha_invariants.py`）：

```
HA RESULT: PASS
  execution_id = HA-20260822-5a25a8e0
  Recovery:
    checkpoint:            PASS
    lease takeover:        PASS
    single owner:          PASS
    idempotency:           PASS
    trajectory continuity: PASS
    final result:          PASS
```

---

## 六、审计表（可证明数据）

- `side_effects`：`effect_key`（execution_id+step_id+effect_type）唯一 → effectively-once 证据。
- `execution_events`：`replica/event/step_id` 时间序 → trajectory 连续性证据。

每个实验生成可证明的 `execution_id = HA-YYYYMMDD-<rand>`。

---

## 七、P0 + H2/H3 修复闭环与最终验收

> 本节记录生产级审计后补齐的最小修复包（commit 链：`741c1e8` → `2019faf`(P0) →
> `c73bb5f`(H3) → `c2a1039`(H2)）。目标：把 HA 从「代码 review 自证」推进到
> 「故障注入 + 运行时真保证」。

### P0（4 Critical，已闭环 `2019faf`）

| # | 问题 | 修复 |
|---|---|---|
| C1 | `execution()` 忽略 acquire 返回值 → 破坏 single-active-owner | **fail-closed**：acquire 失败抛 `ExecutionNotOwned`，不进入执行循环 |
| C2 | `owner=os.getpid()` 多容器 Docker 下都为 1 → fencing 失效 | 改为 `<replica_id>:<uuid>`，跨副本唯一 |
| C3 | checkpoint 无 fencing → stale/zombie writer 可覆盖新 owner | `PgCheckpointStore.save` 改 monotonic version CAS（`WHERE version < EXCLUDED.version OR (resumable=FALSE AND EXCLUDED.resumable=TRUE)`），旧 owner 晚写抛 `FencedWriteError` |
| C4 | `reap_stale_notifying` 用 `SET owner=NULL` 违反 NOT NULL | 改为 `DELETE`，符合 schema |

### H2（High，运行时副作用落库真正生效 `c2a1039`）

- P0 阶段 `side_effects` 表的唯一约束只在**测试桩**（`HAProbeRegistry.execute` 直接写 DB）验证，运行时代码从未调用。
- 修复：新增 `SideEffectStore` ABC + `PgSideEffectStore`（`ON CONFLICT DO NOTHING` 幂等去重，`has()` 供 resume 判断已落地 step）；`PlannerRuntime` 注入 `side_effect_store`；`execution_graph._run` 在 `delegate` 成功后调 `record(execution_id, step_id, skill:<name>, lease_owner)`。
- 生产路径 `execute_plan` 走 `_run_graph_in_place`，同样经此落库（构造 `PlannerRuntime` 时传 `side_effect_store` 即生效）。effectively-once 从「测试自证」变为「运行时真保证」。

### H3（High，layer-gather 所有权丢失窗口 `c73bb5f`）

- 原 `asyncio.gather` 同层并行期间，旧 owner 丢 lease 后，层边界检查会放过本层在途节点继续发起副作用。
- 修复：`_run` 协程在 `delegate` 前自查 `ownership_lost`，已丢失则中止本节点（复用 fatal 终止分支，`error_class=ownership_lost`），保证 single-active-owner。

### 验收状态（最终）

- `tests/ha`：14 passed（含 `test_stale_writer` split-brain 闭环、`test_runtime_side_effect_record` 运行时落库 + 幂等 + resume 可见性）
- `tests/durability`：25 passed（pg_durability 14，含 version CAS / reap DELETE）
- `tests/planner`：63 passed
- **合计 102 passed，零回归**

### H1 处置说明（环境约束）

- H1 原始定义为「测试未真正双容器 kill」。当前 `run_replica_a` 用「手动 acquire 短 ttl 不 release」语义等价 SIGKILL（heartbeat 死亡 → PG lease 过期 → B 接管），在无头环境下已捕获 split-brain / 接管 / 重复副作用的全部语义。
- 真双进程验证已由 `scripts/ha_real_kill_verify.py` 补强：起两个真实 OS 进程（agent-a/agent-b）共享真实 PG，A 在 step_1 后真 `SIGKILL`，B 从 checkpoint 接管；Linux 真实验证 PASS（side_effects 每 step 各 1 条 WRITE + 1 条 skill，无重复）。
- **CI 门禁**：`tests/ha` 全部测试加 `requires_pg` marker（conftest 自动打标 + 连接失败/Windows 平台自动 skip，避免误报）；`.github/workflows/agent-platform-ci.yml` 新增 `ha` job，在 `ubuntu-latest` 起 PostgreSQL 服务容器，跑 `pytest tests/ha -m requires_pg` + 真双进程 kill 脚本。Windows CI 下 HA 测试干净 skip，由 Linux CI 覆盖。

---

## 八、HA Final Hardening（2026-08-22 重新审计结论）

> 完整重审后结论：**没有新的 Critical correctness bug**。剩余主要为 🟠 High/Medium，
> 属架构边界与语义严谨性，不阻塞上线级 HA 验收。本节记录最终硬化动作。

### 8.1 语义边界（最重要，面试可底气陈述）

**不再宣称 Exactly-Once**。v2 实际能力对应的严谨定义：

| 层 | 定义 | 保障来源 |
|---|---|---|
| Execution | **at-least-once** | attempt 可 >1（崩溃重跑） |
| Checkpoint | **durable** | 每节点完成即落盘 |
| Ownership | **single active owner** | PG CAS + `expires_at` 自动过期 |
| Checkpoint write | **stale-writer protected** | `FencedWriteError`（version CAS） |
| Side-effect log | **idempotency evidence** | `side_effects` 唯一约束 |
| Business effect | **requires idempotency boundary** | 业务副作用自身需支持幂等 |

最终：**Effectively-Once** 仅在业务副作用本身支持 `idempotency_key` 或 `transactional outbox` 时成立。
Runtime 层提供的是**幂等证据（idempotency marker）**，而非强制 exactly-once。

### 8.2 H2/H4 修复：heartbeat owner 改为必填

- 原 `heartbeat(execution_id, ttl_s, owner=None)` 保留 `owner=None` 旁路，会绕过 owner fencing，
  未来某调用方 `await ownership.heartbeat(eid, 30)` 可重新引入 split-brain。
- 修复：`owner` 改为**必填参数**（删 `owner=None` 分支），`InMemory` / `Pg` 实现均强制校验
  `cur[0] == owner`。生产主路径（`protocol.py:467` 始终传 `owner=owner`）无影响。

### 8.3 H3 契约明确：SideEffectStore 的 effect_type 约束

- `effect_key = execution_id : step_id : effect_type`，故**同一 step 内每种 effect_type 只能发生一次**。
- 若一个 Skill 合法产生多种业务副作用（如 `WRITE-A` 与 `WRITE-B`），必须使用**不同 effect_type**，
  否则被错误当成重复副作用丢弃。此契约已写入 `SideEffectStore` 类文档。
- **边界**：`record()` 与真实业务副作用**非原子事务**。若「真实副作用 ✔ → 进程 crash →
  record() ✘」，B resume 时二者均无记录 → 重跑 Skill → 真实副作用 ×2。这是 distributed
  side-effect 的 classic atomicity 问题，需业务副作用自身支持幂等/Outbox，非单条 SQL 可解。

### 8.4 H8 测试：最危险崩溃窗口（side-effect / checkpoint 双写窗口）

- 新增 `tests/ha/test_h8_side_effect_before_checkpoint.py`：A 真实执行 step_1（checkpoint1+effect1），
  在 step_2 的 **side_effect 已落、checkpoint 尚未写**的窗口注入 kill；B 从 checkpoint1 resume 重跑 step_2。
- 验证点：step_2 `attempt ≥ 2` 但 `actual effect = 1`（唯一约束兜底），最终 checkpoint 完整。
- 至此故障注入矩阵覆盖：checkpoint 后杀 / checkpoint 前杀 / **副作用后-检查点前杀（最危险窗口）** /
  lease 过期 / 双恢复竞争 / 重复提交 / A→B→C 接管 / invariants。

### 8.5 已知遗留（🟠，不阻塞验收）

| # | 项 | 说明 |
|---|---|---|
| H1 | checkpoint `version = len(completed)` 非严格 fencing token | 当前能挡 stale downgrade，但 version 无法表达"谁更新更晚"。建议未来升级为 lease `generation/epoch`，B 接管 `generation+1`，A 写 `WHERE generation = 7` 严格拒绝。**当前不阻塞**。 |
| H3 | side_effect 与真实业务副作用非原子 | 架构边界，需业务侧幂等，Runtime 仅提供证据 |
| H5 | 心跳非实时强杀 | lease fencing + 幂等副作用为最终方案，不幻想"心跳强杀运行中的 Skill" |

### 8.6 最终评级（2026-08-22）

| 能力 | 评级 |
|---|---|
| Execution identity / PG source-of-truth / Lease CAS / Unique owner | 🟢 |
| Acquire fail-closed / Owner fencing / Heartbeat / Stale recovery | 🟢 |
| Checkpoint durability / stale-writer protection / Real crash / Dual contention / A→B→C | 🟢 |
| Trajectory audit / Side-effect idempotency marker | 🟢 |
| Business side-effect atomicity / True fencing token / Crash-in-side-effect-window | 🟠 |
| Exactly-once | ❌（明确不承诺） |

**结论**：v2 Execution HA 主体已完整，进入下一阶段。面试陈述可底气表达——
> 我们没有把 Agent HA 简化成"多副本+重试"。Runtime 层实现了 durable checkpoint、lease-based
> single ownership、owner fencing、stale recovery、跨进程 crash takeover 与 idempotent
> side-effect boundary，并以真实 PostgreSQL + Linux 双进程 SIGKILL 做故障注入验证。执行语义
> 采用 at-least-once，最终业务结果通过幂等副作用实现 effectively-once，而非不严谨宣称 exactly-once。
