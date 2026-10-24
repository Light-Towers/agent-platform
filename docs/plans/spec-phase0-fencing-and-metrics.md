# Phase 0 Spec：Foundation（V3-6A + V3-1 + V3-5A）

> 状态：**Proposed**
> 关联：Issue #11 V3-1/V3-5A/V3-6A；母文档 `docs/plans/v3-roadmap-breakdown.md` §3/§4/§8
> 范围：**strict fencing epoch（V3-1）+ 轻量 DB migration（V3-6A）+ execution 级 HA metrics（V3-5A 初版）**
> 红线：**不重写 v2 checkpoint 数据模型，只加列；不引入 2PC/consensus/distributed transaction；不实现 Exactly-Once**
> 基线：v3 分支 = v2.0.0 冻结代码

---

## 一、目标

把 v2 的 "checkpoint version 单调 + owner 校验" 提升为 **strict fencing epoch（generation）**：

- 引入 `generation`（ownership epoch）与现有 `version`（checkpoint 推进）**完全解耦**；
- **任何需要证明 execution ownership 的 durable write**（checkpoint / status / side-effect receipt / scheduler ownership）都带 generation 校验；
- 旧 owner 用旧 generation 写 → 拒绝（不只挡 checkpoint，堵住 status/receipt 被旧 owner 改的漏洞）。

同时建立 Phase 0 的 **execution 级 HA 观测**（V3-5A 初版指标），为后续 Phase 提供可验证信号。

---

## 二、现状盘点（已复用，不重复造）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| `ExecutionOwnershipStore` ABC | `planner/durability.py:135` | 加 `generation` 语义，不改 ABC 既有方法签名（向后兼容） |
| `PgExecutionOwnershipStore` | `planner/durability_pg.py:157` | 主改造对象 |
| `InMemoryExecutionOwnershipStore` | `planner/durability.py:170` | 同步加 generation（保证语义一致，测试用） |
| `PgCheckpointStore` | `planner/durability_pg.py:53` | 加 generation 校验（保留 version 单调） |
| `PgSideEffectStore.record()` | `planner/durability_pg.py:371` | 加 generation 校验 |
| `execution_leases` 表 | `agent_runtime/db.py:130` | **V3-6A migration**：加 `generation` 列 |
| `execution_checkpoints` 表 | `agent_runtime/db.py:112` | 已有 `version`；Phase 0 加 `generation BIGINT` 列 |
| 心跳/执行循环 | `planner/protocol.py:447-475` | 接线点：构造 owner、`_heartbeat`、`reap_stale` |
| migration 模式 | `agent_runtime/db.py:122` `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` | **沿用幂等补列模式** |
| otel | `agent_runtime/otel.py` | 复用 tracer，补 execution 级 counters |

**约束**：DB migration 只做 **V3-6A（DB schema migration）**，不做 V3-6B（Execution State Schema migration / compaction / retention）——后者属 v3 后段，避免过度设计。

---

## 三、设计

### 3.1 V3-6A：DB migration（先做，轻量）

在 `agent_runtime/db.py` 的 SCHEMA（`SCHEMA_TEMPLATE`）补列，沿用 `ADD COLUMN IF NOT EXISTS` 幂等模式：

```sql
-- execution_leases：加 ownership epoch
ALTER TABLE execution_leases
    ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0;

-- execution_checkpoints：加写时校验所需 generation
ALTER TABLE execution_checkpoints
    ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0;

-- execution_events：记录每次 transition 的 generation（审计/可观测）
ALTER TABLE execution_events
    ADD COLUMN IF NOT EXISTS generation BIGINT;
```

同时在 `CREATE TABLE IF NOT EXISTS` 默认分支里带上 `generation` 字段定义（新库一次到位），旧库靠 `ALTER` 补列。

> 注意：db.py 用 `SCHEMA_TEMPLATE.replace()`（含裸花括号，不能用 `.format()`），新 DDL 不要引入裸花括号。

### 3.2 V3-1：strict fencing epoch

**核心概念（必须解耦）：**

```text
generation = ownership epoch   → 谁持有 lease（owner 的代数），lease 层
version    = checkpoint 推进    → 状态推进了几次，state 层
```

**`execution_leases.generation` 语义：**
- `acquire` 成功（抢到或接续 stale）时，`generation = 旧值 + 1`（stale 接管递增；全新执行从 1 起）。
- `heartbeat` 仅当 `owner 匹配 AND generation 匹配` 时续租。
- 旧 owner 被接管后，其旧 `generation` 的所有 durable write 都被拒绝。

**改动点（逐文件）：**

#### (a) `PgExecutionOwnershipStore`

```python
# acquire：CAS 抢占，成功时 generation+1（ON CONFLICT 分支递增）
#   - 无行（全新）：INSERT generation=1
#   - 过期/同 owner：DO UPDATE generation = table.generation + 1, owner, expires_at
async def acquire(self, execution_id, owner, ttl_s) -> bool:
    ...
    INSERT INTO execution_leases (execution_id, owner, expires_at, generation)
    VALUES (%s, %s, ..., 1)
    ON CONFLICT (execution_id) DO UPDATE
      SET owner=EXCLUDED.owner, expires_at=EXCLUDED.expires_at,
          generation = execution_leases.generation + 1
      WHERE execution_leases.expires_at < now()
         OR execution_leases.owner = EXCLUDED.owner
    RETURNING execution_id

# heartbeat：加 generation 匹配
async def heartbeat(self, execution_id, ttl_s, owner, generation) -> bool:
    UPDATE execution_leases
    SET expires_at = now() + interval
    WHERE execution_id=%s AND owner=%s AND generation=%s
    RETURNING execution_id
```

> heartbeat 加 `generation` 参数。为向后兼容，ABC 签名给默认 `generation: int | None = None`；`None` 表示"不校验 generation"（仅测试/过渡），生产主路径必须传。**但注意**：v2 已删除 `owner=None` 旁路，generation 的 `None` 旁路应只在内部测试允许，生产调用方一律显式传——文档需写清，避免重蹈 H2 覆辙。

#### (b) 新增 fencing 辅助（读当前 generation）

```python
# PgExecutionOwnershipStore 新增
async def get_generation(self, execution_id) -> int | None:
    """返回当前 lease 的 generation（无/过期返回 None）。"""
```

#### (c) `PgCheckpointStore.save`：加 generation 校验

在现有 version CAS 基础上，**外层加 generation 门**：

```python
async def save(self, checkpoint: Checkpoint, *, generation: int | None = None):
    # generation 非 None 时，校验 checkpoint 行内 generation == 传入 generation
    # 不匹配 → FencedWriteError（旧 owner 用旧 epoch 写，无论 version 如何都拒绝）
```

> checkpoint 表加 `generation` 列；save 时写入当前 owner 的 generation。`WHERE` 条件：`generation` 匹配 且 （version 单调 或 resumable 置位）。这样即使 version 巧合相同（如同一层多节点），旧 owner 的旧 generation 也写不进。

#### (d) `PgSideEffectStore.record`：加 generation 校验

`side_effects` 表加 `generation BIGINT` 列；`record()` 写入时带当前 owner generation；仅当该 effect 尚不存在（ON CONFLICT DO NOTHING）时写入。**旧 owner 的迟到 record 因 owner 不再是当前持有者、generation 不匹配，应在调用层被拒**（见 3.2e）。

> record 本身是 INSERT ... DO NOTHING（幂等），generation 主要用于**审计**（证明哪一代 owner 写入），不改变幂等去重逻辑。

#### (e) 执行循环接线（`planner/protocol.py`）

- 构造 owner 后，首次 `acquire` 返回成功时**拿回当前 generation**，缓存为 `self._current_generation`（contextvar 或局部变量）。
- `_heartbeat` 协程调 `heartbeat(eid, ttl, owner, generation=self._generation)`；失败（返回 False 或抛）→ 置 `ownership_lost`。
- `execute_plan` 内所有 durable write（checkpoint.save / side_effect.record / status transition / trajectory persist）都**带当前 generation**。
- `reap_stale_executions`（`planner/durability.py:216`）与 `pg_reap_stale`（`durability_pg.py:337`）在回收时读取并保留 generation（stale 接管由 B 的 acquire 完成 generation+1，reaper 不需要动 generation）。

### 3.3 V3-5A：execution 级 HA metrics（初版）

在 `agent_runtime/otel.py` 补一组 **execution 级 counter/histogram**（复用现有 otel，无独立后端）：

```python
# 指标（初版，最小集）
EXECUTION_TOTAL         # counter，execution 启动/完成
ATTEMPT_TOTAL           # counter，attempt 数（owner 变更即 +1）
TAKEOVER_TOTAL          # counter，B 接管成功次数（acquire 时旧 owner != 新 owner）
TAKEOVER_LATENCY        # histogram，接管延迟（lease 过期→acquire 成功）
CHECKPOINT_LAG          # gauge，resume 时从 checkpoint 到最新 state 的滞后（step 数）
RECOVERY_TOTAL          # counter，stale recovery 触发次数
STUCK_TOTAL             # counter，stuck execution 检测次数（Phase 后段接 scheduler）
```

埋点位置：
- `protocol.py` acquire 成功 → `ATTEMPT_TOTAL`、接管时 `TAKEOVER_TOTAL` + `TAKEOVER_LATENCY`
- `execution_graph._run` checkpoint save → `CHECKPOINT_LAG`
- `reap_stale` → `RECOVERY_TOTAL`

> V3-5A 只做**指标采集**（counter/histogram），**不做** V3-5B Control Plane / Replay/Debug UI（后置，Phase 4）。

---

## 四、验收标准

### V3-6A（migration）

- [ ] 新库执行 SCHEMA：`execution_leases` / `execution_checkpoints` / `execution_events` 均含 `generation` 列
- [ ] 旧库（无 generation 列）执行 SCHEMA：幂等补列成功，不报错、不丢数据
- [ ] `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 可重复执行（幂等）

### V3-1（strict fencing）

- [ ] **新测试 `test_generation_fencing`**：A acquire gen=1 执行 → B 接管（gen=2）→ A 残活写 checkpoint（带 gen=1）→ 被 `FencedWriteError` 拒绝，B 的 checkpoint 不被降级覆盖
- [ ] **status transition 也被 fence**：旧 owner 用旧 generation 改 execution status → 拒绝（新增断言，不只 checkpoint）
- [ ] heartbeat 带 generation：B 接管后，A 用旧 generation heartbeat → 返回 False → A 中止
- [ ] 现有 HA 故障矩阵（`tests/ha`）**零回归**：generation 引入不破坏 single-owner / H8 crash-window / A→B→C 接管
- [ ] `version` 与 `generation` 解耦：同 layer 多节点推进（version 变）不误触 generation 递增；generation 只在接管时 +1

### V3-5A（metrics）

- [ ] 一次 A→B 接管后，`ATTEMPT_TOTAL` 至少 2、`TAKEOVER_TOTAL=1`、`TAKEOVER_LATENCY` 有值
- [ ] stale 回收后 `RECOVERY_TOTAL` +1
- [ ] checkpoint 推进时 `CHECKPOINT_LAG` 可观测

---

## 五、影响面与风险

| 影响面 | 评估 |
|---|---|
| `planner/durability.py` ABC | 加 `get_generation`（抽象方法），InMemory 同步实现；`reap_stale_executions` 微调 |
| `planner/durability_pg.py` | 主改造（acquire/heartbeat/checkpoint.save/side_effect.record） |
| `planner/protocol.py` | 执行循环接线：owner+generation 传递、durable write 带 generation |
| `agent_runtime/db.py` | SCHEMA 补 generation 列（幂等） |
| `agent_runtime/otel.py` | 新增 execution 级 counters/histograms |
| `tests/ha` | 新增 `test_generation_fencing`；既有矩阵零回归 |
| 风险 | heartbeat/checkpoint 签名变更影响调用方 → 用默认参数兼容 + 文档强制生产传 generation；**严禁**用 `generation=None` 旁路走生产路径（对标 v2 H2 owner=None 教训） |

**不改动**：checkpoint 数据模型语义（不重写 version 逻辑）、idempotency/ownership 语义、execution 状态机结构、V3-6B compaction/retention、V3-2 Effect Contract、V3-3 ExternalTask、V3-4 Scheduler、V3-5B Control Plane。

---

## 六、交付物

| 文件 | 动作 |
|---|---|
| `packages/agent-runtime/agent_runtime/db.py` | SCHEMA 补 generation 列 |
| `packages/agent-runtime/agent_runtime/planner/durability.py` | ABC + InMemory 加 generation 语义 + `get_generation` |
| `packages/agent-runtime/agent_runtime/planner/durability_pg.py` | acquire/heartbeat/checkpoint.save/side_effect.record 加 generation |
| `packages/agent-runtime/agent_runtime/planner/protocol.py` | 执行循环接线 + durable write 带 generation |
| `packages/agent-runtime/agent_runtime/otel.py` | execution 级 HA metrics |
| `tests/ha/test_generation_fencing.py` | 新增 strict fencing 测试 |
| `tests/ha/`（既有） | 回归验证（零回归） |

---

*Spec 规划文档。实现阶段以本文为母文档，先做 V3-6A migration，再落地 V3-1，最后接 V3-5A 埋点。*
