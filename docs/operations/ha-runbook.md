# Execution HA 运维 Runbook（v2）

> 适用版本：**v2（冻结前收尾）**。本文档面向**生产运维人员**，提供可执行的 HA 故障处理手册。
> 不修改任何 Runtime 代码，仅描述现有 `ExecutionOwnershipStore` / `CheckpointStore` /
> `SideEffectStore` 的行为与运维操作。
>
> 设计总述见 `docs/ha/ha-durable-execution.md`。

---

## 1. 核心概念

### 1.1 Execution Lease 是什么

每个正在执行的 `execution_id` 由**一个副本**持有 lease（租约）。租约记录：

```text
execution_id → (owner = replica_id:uuid, expires_at)
```

- **single active owner**：同一时刻只有一个副本能持有有效 lease。
- lease 由 `ExecutionOwnershipStore` 管理（PG 为 source of truth）。
- owner 格式 `<replica_id>:<uuid>`，保证跨容器/跨进程唯一（避免 Docker 下 pid=1 冲突）。

### 1.2 heartbeat / TTL 的关系

- 执行期间副本定期 `heartbeat(execution_id, ttl_s, owner)` 把 `expires_at` 顺延 `ttl_s`。
- `owner` 为**必填**（v2 已删除 `owner=None` 旁路，防 split-brain）。
- 若 `heartbeat` 返回 `False`：说明 lease 已被其他副本接管 → 当前副本感知
  `ownership_lost` → 执行循环协作式中止，**旧 owner 不再产生副作用**。
- TTL 配置建议：大于正常心跳间隔的 2~3 倍，避免网络抖动误判。

### 1.3 如何判断 execution stale

stale 定义：**租约已过期且仍持有**（即 `expires_at <= now` 且仍在 ownership 表中）。

- 正常执行：heartbeat 不断续租，`expires_at` 始终在未来 → 非 stale。
- 副本 crash / 网络分区：heartbeat 停止 → `expires_at` 到期 → 变 stale。
- `list_stale(now)` 返回所有 stale 的 `execution_id`。

### 1.4 checkpoint 的作用

- `CheckpointStore` 按 `execution_id` 持久化**已完成节点结果**（`completed`）。
- 每节点完成即落盘（durable），崩溃后可基于同一 `execution_id` resume。
- checkpoint 带 `version`（单调递增）+ `resumable` 标志。
- `resumable=True` 表示所有权已释放，可被其他副本 resume 接管。

### 1.5 replica crash 后正常恢复流程

```text
A 执行中 crash / 网络分区
   │ heartbeat 停止
   ▼
A 的 lease expires_at 到期 → execution 变 stale
   │
   ▼
B（另一副本）检测到 stale → acquire 成功（CAS）
   │
   ▼
B 从 checkpoint.load 复用已完成节点 → 继续未完成任务
   │
   ▼
B 完成 → release lease
```

前提：B 能访问**同一 PostgreSQL**（source of truth）。若 B 是不同 PG 实例则无法接管。

---

## 2. 手动触发 stale execution reap

`reap_stale_executions()` 逻辑（进程内可单测，跨进程唤醒属环境依赖）：

```python
# 伪代码 / 运维脚本参考（逻辑层）
stale = await ownership.list_stale(now)
for eid in stale:
    cur_owner = await ownership.get_owner(eid)
    if cur_owner is not None:
        await ownership.release(eid, owner=cur_owner)
    cp = await checkpoint_store.load(eid)
    if cp is not None:
        cp.resumable = True          # 标记可被 resume 接管
        cp.updated_at = now
        await checkpoint_store.save(cp)
```

操作原则：

- **reap 只释放所有权 + 标记 checkpoint resumable**，不删除任何数据。
- 真正"唤醒 B 去 resume"由运行环境保证（如调度器 / 副本健康检查），v2 不在 Runtime 内做。
- 手动 reap 前确认目标 execution 确实无活 owner（见 §3 排查），避免误释放正常执行。

---

## 3. 数据保留原则

| 数据 | 保留原则 |
|---|---|
| `execution_events` | 审计轨迹，长期保留（按合规策略） |
| `side_effects` | effectively-once 证据，保留至 execution 生命周期结束；删除需谨慎（影响 resume 判断） |
| `checkpoint` | 保留至 execution 完成或显式清理；`resumable=True` 的 checkpoint 可被 resume 复用 |
| `ownership` | 活 lease 随执行存在；stale 应被 reap 清理，避免表膨胀 |

**不要手动 DELETE checkpoint / side_effects**，除非你清楚该 execution 已永久终止且不再 resume。

---

## 4. 故障排查

### 4.1 execution stuck（卡住不推进）

可能原因：
- 持有 owner 的副本假死（心跳协程阻塞），lease 未释放但未推进 checkpoint。
- 下游 Skill 阻塞（外部 API 超时未设上限）。

排查：
1. 查 `ownership` 表该 `execution_id` 的 `expires_at` 是否在未来（owner 还在但未推进）。
2. 查 `execution_events` 最新事件时间，判断是否长时间无新事件。
3. 若确认 owner 副本已不可用，等 lease 自然过期 → 触发 §2 reap → 其他副本接管。
4. 检查对应 replica 进程是否存活 / 日志是否阻塞在外部调用。

### 4.2 ownership lost（失去所有权）

现象：`heartbeat` 返回 `False`，执行循环中止。

原因：
- 其他副本已接管（正常 failover）。
- 本副本时钟漂移导致误判（罕见）。

排查：
1. 查 `ownership` 表该 `execution_id` 当前 `owner` 是否为本副本。
2. 若 owner 已是其他副本 → 正常，本副本应已停止（无需干预）。
3. 若怀疑误接管：比对两副本系统时钟；审查 lease TTL 是否过短。

### 4.3 repeated recovery（反复恢复 / 接力）

现象：A→B→C 不断接管同一 execution。

原因：
- 每次接管后新 owner 也很快 crash（如 Skill 必然抛错）。
- lease TTL 过短，B 还没完成 heartbeat 就过期。

排查：
1. 查 `execution_events` 的 owner 序列，是否频繁切换。
2. 查新 owner 日志是否有必然失败（如缺配置、外部依赖不可用）。
3. 调大 TTL 或修复新 owner 的崩溃根因（非 Runtime 问题）。

### 4.4 checkpoint 不推进

现象：checkpoint 的 `completed` 节点数不增长。

原因：
- 当前 step 的 Skill 卡住（外部阻塞）。
- checkpoint 写入被 `FencedWriteError` 拒绝（旧 owner 试图覆盖新 owner，应被拒）。

排查：
1. 查 `execution_events` 是否有新节点完成事件。
2. 若有 `FencedWriteError` 日志：说明是 stale writer 被挡（正常防护），确认当前 owner 是唯一有效 writer。
3. 若 Skill 卡住：参考 §4.1 处理。

### 4.5 side effect duplicate（副作用重复）

现象：外部系统收到重复副作用（如重复邮件）。

原因：
- 业务副作用本身不幂等，且执行在「副作用 ✔ → record() ✘」窗口崩溃 → B 重跑。
- 多副本同时执行同一 step（single-owner 不变量被破坏，极罕见）。

排查：
1. 查 `side_effects` 表该 `(execution_id, step_id, effect_type)` 是否只有 1 条（`effect_key` 唯一约束应保证）。
2. 若 `side_effects` 只有 1 条但外部仍重复 → **业务副作用不幂等**（见 `side-effect-tool-contract.md` 第 6 节），需修复 Tool 而非 Runtime。
3. 若 `side_effects` 有多条 → 严重异常（唯一约束失效），立即检查 PG schema / 多写路径。

---

## 5. 正常故障恢复 vs 人工介入边界

| 场景 | 谁处理 | 运维动作 |
|---|---|---|
| 副本 crash，lease 自然过期 | Runtime 自动 | 无需干预，B 自动接管 |
| 网络分区恢复 | Runtime 自动 | 旧 owner 感知 ownership_lost 中止 |
| stale execution 检测 | Runtime / 调度器 | 可选手动 reap（§2） |
| 外部依赖不可用导致 Skill 失败 | 业务侧 | 修复外部依赖，重投 execution |
| 数据误删 / schema 损坏 | 人工 | 从备份恢复 PG（见 §6） |
| 反复 recovery | 人工分析 | 查根因（§4.3） |

**边界**：v2 的自动恢复覆盖"副本级 crash + lease 过期 + resume"。**不覆盖**外部依赖故障、
业务逻辑错误、数据损坏——这些需要人工或业务侧处理。

---

## 6. PostgreSQL 异常处理原则

- **PG 是 source of truth**：所有 lease / checkpoint / side_effect 以 PG 为准。
- PG 不可达时：
  - 执行中的副本 heartbeat 失败 → 感知 ownership_lost → 中止（fail-closed，不破坏 single-owner）。
  - 新 execution 无法 acquire → 整体不可用，需恢复 PG 连接。
- **不要**在 PG 恢复过程中手动改 ownership / checkpoint 表，避免引入不一致。
- PG 数据损坏：从最近备份恢复；恢复后 stale 检测会重新接管未完成 execution。
- 连接池 / 网络抖动：依赖 PG 自身的 `expires_at` 自动过期机制，无需人工清 lease。

---

## 7. 常见误操作及禁止事项

| 禁止事项 | 原因 |
|---|---|
| 手动 `UPDATE ownership SET owner=NULL` | 违反 NOT NULL；正确做法用 reap（DELETE/释放） |
| 手动 DELETE checkpoint / side_effects | 破坏 resume 与 effectively-once 证据 |
| 调小 lease TTL 到心跳间隔以下 | 导致频繁误接管 / repeated recovery |
| 给 heartbeat 传 `owner=None` | v2 已删除该旁路；任何调用方必须传 owner |
| 跨 PG 实例尝试 failover | 不同 PG 无法共享 lease / checkpoint |
| 为"保证 exactly-once"引入 2PC | 超出 v2 边界，破坏架构冻结 |
| 直接改 `effect_key` 拼接逻辑 | 会破坏幂等去重契约 |

---

## Incident Checklist

```text
Incident Checklist
====================
[ ] 1. 收集 execution_id / replica_id / 近似发生时间
[ ] 2. 查 ownership 表：当前 owner？expires_at？是否 stale？
[ ] 3. 查 execution_events：最后事件时间？owner 切换序列？
[ ] 4. 查 checkpoint：completed 节点数？是否 resumable？
[ ] 5. 查 side_effects：该 step 的 effect_key 是否唯一（应 1 条）？
[ ] 6. 判断类型：stuck / ownership_lost / repeated_recovery / checkpoint停滞 / 副作用重复
[ ] 7. 若是副本 crash：等 lease 过期 → 确认 B 接管 → 观察完成
[ ] 8. 若是外部依赖故障：修复依赖 → 重投 execution
[ ] 9. 若是数据损坏：从备份恢复 PG → 重新 stale 检测
[ ] 10. 记录根因与处置，更新运维知识库
```

---

## Recovery Decision Tree

```text
execution 无进展？
│
├─ lease 仍有效（expires_at 在未来）？
│   ├─ 是 → owner 副本是否存活？
│   │        ├─ 是 → Skill 卡在外部调用 → 查外部依赖 / 超时配置
│   │        └─ 否 → 等 lease 自然过期（不要手动强删）
│   └─ 否（已 stale）→ 进入 reap 流程
│
├─ reap 流程
│   ├─ 确认无活 owner（ownership 表 owner 非预期副本）
│   ├─ release ownership
│   ├─ 标记 checkpoint resumable=True
│   └─ 等待 / 触发其他副本 resume
│
├─ resume 后副作用重复？
│   ├─ side_effects 表 effect_key 唯一（1 条）？
│   │   ├─ 是 → 业务副作用不幂等 → 修 Tool（见 side-effect-tool-contract.md）
│   │   └─ 否（多条）→ 严重异常 → 查 PG schema / 多写路径
│   └─
│
├─ 反复 recovery（A→B→C）？
│   ├─ 每次新 owner 是否必然崩溃？ → 修崩溃根因（业务/配置）
│   └─ TTL 是否过短？ → 调大 TTL
│
└─ PG 不可达？
    ├─ 执行中副本 → 应 fail-closed 中止（正常）
    ├─ 恢复 PG → stale 检测重新接管
    └─ 数据损坏 → 从备份恢复，不要手动改表
```

---

*本文档为 v2 Release 收尾产物，配合 `docs/ha/ha-durable-execution.md` 与
`docs/operations/side-effect-tool-contract.md` 使用。不修改任何 Runtime 代码。*
