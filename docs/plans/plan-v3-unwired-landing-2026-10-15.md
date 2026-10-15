# 方案：V3「未接线半成品」转正批（state_migration / execution_recovery / requeue+recover / receipt fencing / skill_router）

> 状态：**部分落地 4/5**（分支 `feat/v3-unwired-modules-landing-2026-10-15`，**未部署**）｜ 依据：本机实跑 `ruff check .` / `scripts/check_doc_sync.py` / `scripts/lint_architecture.py` 全 rc=0；pytest 五 session 全绿 = agent-runtime 609 + agent_server 100 + 联邦 176 + exhibition 352 +（根 session 见提交信息），含本批新增 24 + 4 条 ｜ 回写：项 1/2/3/5 已落地，**项 4（receipt fencing）未开工**，成因与残差见 §5；真 PG / 双实例验收仍属「待环境」

分支：`feat/v3-unwired-modules-landing-2026-10-15`。本轮**只改代码 + 补测试，不部署**（126 夜间关机），凡需真集群/真 PG 的判据一律标为「待环境」，不得当成已验证。

## 1. 目标与范围

把 `docs/TODO.md` §2/§3 里「代码与单测俱在、主链路零调用」的五项接线，使 V3 缺口 1/4/8 的未闭合面收窄。逐项现状（2026-10-15 对码实取，不引台账结论）：

| # | 项 | 现状证据 | 目标 |
|---|---|---|---|
| 1 | `state_migration` | `planner/durability.py:60-61` 每个 checkpoint 已盖 `CURRENT_STATE_SCHEMA_VERSION`，`planner/durability_pg.py:95-96` 的 `load()` 已调 `migrator.migrate()`；但构造函数 `durability_pg.py:68` 默认 `migrator=None`，且**两个生产调用点都没传**（`applications/agent_server/main.py:72`、`applications/agent_federation/planners/__init__.py:51`）⇒ 迁移在生产**从不执行** | 两个调用点注入 `get_default_migrator()` |
| 2 | V3 缺口 4 `reschedule` | `execution_scheduler.py:645-668` 的 `SchedulerReaper.run()` 对 lease 失效执行只做 `complete(FAILED)`（`:661`），**不重新排队**；`execution_recovery.py` 的 `RecoveryManager.decide`/`Rescheduler.execute`（`:117-205`）已实现且被 `tests/test_execution_recovery.py` 覆盖，但生产 import 为 0 | Reaper 在**保留 lease 安全门**的前提下接恢复决策 |
| 3 | V3 缺口 8 `requeue`/`recover` | `control_plane.py` 只有 6 个动作（`inspect:97`/`pause:162`/`resume:183`/`cancel:204`/`retry:241`/`terminate:272`），`api/control.py` 端点 1:1 对应；全仓无 `requeue`、无 `recover` | 补 2 个动作 + 2 个端点 |
| 4 | V3 缺口 1 receipt fencing | `AwaitableTask`（`awaitable_task.py:130-151`）**无 generation 字段**；`PgSideEffectStore.record`（`planner/durability_pg.py:416-437`）是裸 `INSERT … ON CONFLICT DO NOTHING`；已 fenced 的是 checkpoint（`durability_pg.py:107-146`）/ execution status（`execution_state_pg.py:83-111`）/ ownership generation（`durability_pg.py:215-223`）⇒ 3/5 | 两类 receipt 补 generation fence |
| 5 | exhibition `skill_router` | `foundation/skill_router.py:167` 的 `route()` 生产调用点为 **0**；`graph/nodes.py:55-136` 的 `run_skill` 走本地 `_SKILLS` dict（`:30-33`/`:66`）直接 `skill.run()`（`:87`），`skills/venue_schedule_query.py:75` 直连 `ctx.warehouse_client` ⇒ scope 校验与 readiness 拦截被绕过 | 按 TODO 既定方向 `run_skill → route(...) → 执行` 接线 |

**不在本轮范围**（避免把「未完成计划」无限外延）：
- `human_task` / `payload_externalization` 接线——两者虽同为「零生产调用」，但接线点分别落在 planner 中断语义与 context assembler 预算链上，影响面大于本批，需独立方案。
- `plan-intent-embedder-bypasses-provider-2026-10-10.md`（选项 A/B/C **待用户拍板**）与 `plan-router-keyword-gate-hides-corpus-2026-10-12.md`（同）——待拍板项不代做决定。
- 删除重复的 `PgAwaitableTaskStore`（`awaitable_task_pg.py:23` 与 `execution_state_pg.py:114` 各一份）：生产接线的是前者（`main.py:400-402`），后者仅被 `working_memory.py` 的 docstring 提及。合并属重构，按红线另出方案；本轮只保证**生产那一份**被 fenced，并把重复事实登记在 §5。

## 2. 影响面

| 项 | 改动文件 | 行为变更 | 默认值 |
|---|---|---|---|
| 1 | `applications/agent_server/main.py`、`applications/agent_federation/planners/__init__.py` | checkpoint `load()` 起真跑 schema 迁移链 | 无注册迁移时 `v1 == CURRENT`，`migrate()` 原样返回 ⇒ **零行为变更**，只是把能力接上 |
| 2 | `packages/agent-runtime/agent_runtime/execution_scheduler.py`、`applications/agent_server/main.py`、`applications/agent_server/config.py` | lease 失效的执行不再无条件 FAILED，改按 Effect Contract 决策（retry/query/fail/human）；retry 会**新入队一条 `:retry:N`**，占用队列容量 | `scheduler_recovery_enabled` 默认 **False**（与 `scheduler_enabled` 同为渐进开启）；关闭时逐字保持现行为 |
| 3 | `packages/agent-runtime/agent_runtime/execution_scheduler.py`（`SchedulerStore` 新增 `requeue`）、`control_plane.py`、`applications/agent_server/api/control.py` | 新增能力，不改既有 6 个动作 | `requeue` 只允许 `FAILED`/`CANCELLED`/`DISPATCHED` → `QUEUED`；`COMPLETED`/`QUEUED`/`RUNNING` 拒绝 |
| 4 | `packages/agent-runtime/agent_runtime/awaitable_task.py`、`awaitable_task_pg.py`、`execution_state_pg.py`、`planner/durability_pg.py`、`db.py` DDL、新迁移文件 | 旧 generation 的 receipt 写入被原子拒绝并抛错，不再静默覆盖 | `generation=None` 时退回现有语义（向后兼容，同 checkpoint 的 `durability_pg.py:113-115` 处置） |
| 5 | `applications/exhibition-agent/**` | skill 调用改经路由门禁；scope 不符 / readiness 未就绪会**拦截**而非静默执行 | 由子任务实现，验收见 §4 |

**红线自查**：项 2/3/4 全在 `packages/agent-runtime` 与 `applications/`，依赖方向仍是 `application → agent-runtime → agent-core`，无反向 import。`execution_recovery` 已 import `execution_scheduler`，故 `execution_scheduler` **不得**模块级 import 它（会成环）——用运行时局部 import + `TYPE_CHECKING` 注解，代码里注明这条 WHY。

## 3. 迁移策略

- **代码兼容**：项 2/3 全部走「新参数默认关闭 / 新方法新增」，既有调用点不传即保持旧行为，无破坏性签名变更。
- **schema 变更（项 4）**：`awaitable_tasks` 加 `generation` 列走仓内既有迁移链（`db/migrations/`，`schema_migrations` 元表），新列可空 + 默认 `NULL`，旧行不需回填；读路径 `r[15]` 取值后按 `None` 退回无 fence 语义。
  - ⚠️ 已知坑：迁移文件 checksum 在 Windows 工作区是 CRLF，比对须用 `git show <sha>:<path>` 取 blob，不能直接读本机文件（曾造出「checksum 漂移 ⇒ 启动崩」的假阳性）。
- **回滚**：项 2/3 关开关即回滚；项 4 回滚需保留新列（列存在但代码不读即无影响），不删列。
- **部署**：本轮不部署。项 4 的迁移在现网执行前须先 dry-run 备份，属「待环境」判据。

## 4. 验收标准

本机可跑（本轮必须全绿）：
1. `uv run --with ruff ruff check .` rc=0（新增代码不得引入 `BLE001`/`S110`）。
2. `uv run python scripts/lint_architecture.py` rc=0（含 P12 等 16 条不变量）。
3. `uv run python scripts/check_doc_sync.py` rc=0。
4. `uv run pytest packages/agent-runtime/tests -q` 全绿，且**新增用例覆盖**：
   - 项 1：两个生产调用点构造出的 `PgCheckpointStore._migrator is not None`（钉住「装配」而不只是「实现存在」）；
   - 项 2：lease 失效 + 开关开 ⇒ 走 retry 且新 id 入队；lease **仍有效** ⇒ 一律跳过（安全门未被绕过）；开关关 ⇒ 逐字保持 `complete(FAILED)`；重试次数超 `max_retries` ⇒ 强制 FAILED；
   - 项 3：`requeue` 三种允许态成功、三种拒绝态返回 False；`recover` 按 contract 返回对应动作；
   - 项 4：旧 generation 写 receipt 必抛、`generation=None` 退回旧语义、side effect 同。
   - 「剥掉防线必红」自证：把项 2 的 lease 门去掉后，对应用例必须失败（证明用例真在测门禁，不是恒真断言）。
5. `uv run pytest applications/agent_server/tests -q` 与 `uv run pytest applications/exhibition-agent/tests -q` 全绿。
6. 新增/改动的用例数只增不减；**禁止删用例、收窄断言、放宽前置条件凑绿**（仓库红线）。

待环境（本轮不判定，不得声称已验证）：
7. 真 PG 上项 4 的迁移可执行 + fence 在并发双写下真拒绝。
8. 双实例物理故障转移端到端验收（`docs/TODO.md` §2 该开项的判据本身）。

## 5. 登记而不粉饰

- **项 4（receipt fencing）本轮未开工**：它需要 `awaitable_tasks` 加 `generation` 列 + 一份新迁移文件 + `PgSideEffectStore.record` 的 owner-generation 守卫，而迁移在现网执行前须先备份 dry-run；126 夜间关机 ⇒ 无法完成「真 PG 上并发双写被拒」这条判据。设计已定（§2/§3 的项 4 行），**不在无环境时半做**——只改 Python 侧而不上迁移会造出「代码读 `r[15]`、表里没有该列」的启动崩。缺口 1 因此仍是 **3/5**。
- 项 2 打开后，`Rescheduler._retry` 会向队列新入一条请求 ⇒ **重试会消耗队列容量**，`QueueFull` 时重试静默失败（`execution_recovery.py:201-205` 只 warning）。默认关就是为此。
- 项 2 的 `contract_resolver` 本轮无生产实现可接（Effect Contract 由 planner 侧持有），默认 `None` ⇒ 决策退化为「无契约默认可重试」（`execution_recovery.py:135-136`）。这是**能力接上、语义待补**，不等于已按契约恢复。
- `PgAwaitableTaskStore` 双份定义本轮不合并，重复事实留在本行；`execution_state_pg.py:114` 那份仍无 fence，但它无生产调用点。
- 项 3 的 `recover` 复用 `execution_recovery`，因此它是「缺口 8」与「§3 execution_recovery 未接线」的共同收口点。
- 项 3 顺带补了一处**装配漏接**：`main.py` 构造 `ControlPlane` 时从未传 `awaitable_store`（形参一直存在），⇒ `inspect()` 的 `external_tasks` 段在生产恒为空。已补传，属缺口 8「inspect 不完整」的一部分。
- **项 5（exhibition skill_router）是部分落地**：门禁已能拦截（scope 不符 / readiness SYNTHETIC 均在 `skill.run` 之前返回 denied，`warehouse.get_rest` 零调用，有 4 条用例钉住），但 TODO 原句的「`route(...)` → 执行」中**「用 route 返回的 endpoint 驱动实际 REST 调用」未做**，执行仍走 skill 自己的 `WarehouseClient`。⇒ 该 TODO 项**不得翻勾**。另：门禁落在 dispatch 节点而非 `BaseSkill` 内，直接调 `skill.run(...)` 的既有用例仍绕过门禁（测试面，非生产调用方）。
