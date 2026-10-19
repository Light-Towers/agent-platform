# V3 缺口 7 残留：payload blob retention/GC（2026-10-19）

- 来源：TODO §2 V3 缺口 7 残留（「blob 无 retention/GC，且与 PG 非同事务——写 blob 成功而 checkpoint 被 fence 拒绝 ⇒ blob 泄漏，同 §HA H3 同族」）
- 类型：运维能力补齐（消无界增长），**非**事务性修复

## 1. 范围切分（诚实边界）

TODO 把两件事捆在一起：**(a) 无 retention/GC**（无界增长）与 **(b) 与 PG 非同事务**（fence 拒绝即泄漏单体）。本项只做 (a)：

- (b) 的正解是「外部化写意图 + 确认」的索引表（blob key ↔ execution_id，PG 事务内确认）⇒ 需新迁移，属独立项（下文 §4 登记）；
- (a) 的 age-based sweep 能把泄漏面的**存量**清掉、把增长**压平**，即使 (b) 未修也不再无界。

## 2. 设计

### 2.1 sweep 能力（payload_externalization.py）

- `PayloadStore` 契约加 `list_keys()` 与 `key_age_s(key)`（InMemory 记插入时刻；FileSystem 用 mtime——两者都用 wall-clock，口径一致）；
- `ExternalizationConfig.gc_min_age_hours: int = 168`（7 天）；
- `PayloadExternalizer.sweep(min_age_seconds=None) -> SweepReport{scanned, deleted, skipped_young, errors}`：只删**年龄 ≥ min_age** 的 blob；年轻的一律不动（在途 checkpoint 的引用不会被打扫误伤——age 下限即安全边际）；单 key 删除异常计入 errors 不中断；
- **安全论证**：load 路径对缺失 blob 本就优雅降级（返回 reference + 告警，2026-10-15 落地行为）⇒ 即便误删仍有可观测降级而非静默错；age 下限（7d）远超 checkpoint 活跃期，双重保险。

### 2.2 周期触发（execution_scheduler.py）

`SchedulerReaper` 增可选 `sweep_callbacks: list | None`：每周期扫描后顺序执行，逐个 try/except（一个 sweeper 抛错不得杀死 reaper——reaper 自身循环已有同款容错）。默认 None ⇒ 行为逐字不变。

### 2.3 装配（agent_server/main.py）

externalization 启用且 externalizer 在场时，传 `[lambda: externalizer.sweep()]` 形态的回调；特性默认关（`PAYLOAD_EXTERNALIZATION_ENABLED`）⇒ 不启用时 reaper 无回调，现值保持。

## 3. 改动清单

1. `payload_externalization.py`：store 契约两方法 + 两实现 + config 字段 + `sweep`；
2. `execution_scheduler.py`：`SchedulerReaper(sweep_callbacks=...)` + 周期执行 + 容错；
3. `main.py`：装配块按 externalization 开关传回调；
4. 测试：sweep 删老/留新/报告形状/单 key 异常不中断；reaper 执行回调且容错；
5. TODO §2 缺口 7 残留订正（(a) 清零、(b) 转独立项）。

## 4. 登记（不粉饰）

- **(b) 事务性修复未做**：需新增 `payload_blob_index` 表（迁移）+ 外部化写意图/确认两段式 ⇒ 独立项，本项只压平增长不清零泄漏单体；
- sweep 是**保守删除**：年龄判据不查引用（查引用需全 checkpoint 扫描，成本不当）⇒ 依赖「age 下限 + load 优雅降级」双保险，不追求精确孤儿判定；
- 本机验证：真 PG 端到端的 GC 效果需环境（与缺口 1/7 既有的"待环境"一致）。

## 5. 验收

- 新测试全绿；agent-runtime / agent_server 会话不减分（23 个存量环境失败计数不变）；
- ruff / docsync rc=0；
- 「剥掉防线必红」：`sweep_callbacks` 执行路径删除 ⇒ reaper 测试红。

## 6. 回滚

单 commit，`git revert` 回退；回退后无 GC（回到无界增长，但无行为破坏）。
