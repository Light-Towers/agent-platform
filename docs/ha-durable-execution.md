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
- 真双容器（docker-compose 起两个 agent 进程 + `docker kill agent-a`）属环境级验证，`docker-compose.ha.yml` 已就绪，可在有 Docker 的环境中补一组端到端 kill 实验；当前模拟覆盖的语义不变，故 H1 记为「环境约束下已覆盖」而非阻塞项。
