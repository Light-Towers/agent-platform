# 方案：V3「未接线半成品」转正批（state_migration / execution_recovery / requeue+recover / receipt fencing / skill_router）

> 状态：**5/5 项已落地**（分支 `feat/v3-unwired-modules-landing-2026-10-15`，**未部署**）｜ 依据：本机实跑 `ruff check .` / `scripts/check_doc_sync.py` / `scripts/lint_architecture.py` 全 rc=0；pytest = 根 683 passed+28 skipped、agent-runtime 631、agent_server 100、联邦 176、exhibition 357；本批新增用例 24+10+4+22+5，既有用例零删改（`test_skill_venue_schedule.py` 的 6 处 fixture 只补 `routed_endpoint=` 输入，断言逐字未改）；项 4 做过「剥掉 fence 必红」自证（把 `is_stale_generation` 短路成恒 False ⇒ 2 条用例转红）｜ 回写：仅剩**待环境**判据（真 PG 并发双写被拒、双实例故障转移）与 §5 登记的 4 条残留；`docs/TODO.md` §3 的 `skill_router` 项已按判据翻勾（本批唯一翻转，计数口径见 §0 追记）

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

- **项 4（receipt fencing）已落地，但两类回执的 fence 形状不同，这个差别是本项的要点**：
  - `awaitable_tasks` 是 upsert（`ON CONFLICT DO UPDATE`）⇒ 可用**行级** generation 比较，PG 侧照抄 checkpoint 的形状（`WHERE … EXCLUDED.generation >= 表.generation` + `RETURNING` + 无行即抛 `FencedWriteError`），InMemory 侧用 `is_stale_generation()` 同判据；两侧都做了 **COALESCE 防降级**——来源未知（`generation=None`）的写入放行，但不得把已知 generation 抹成 NULL，否则一次无 generation 的写就永久解除 fence。
  - `side_effects` 是 **insert-only**（`ON CONFLICT DO NOTHING`）⇒ 冲突时压根不写，**行级比较无从下手**。真正的危害是 zombie writer 抢在新 owner 之前插入 `effect_key`，让新 owner 的 `has()` 判为"已落地"从而**跳过真实副作用**。故 fence 的权威来源只能是 `execution_leases` 的当前 generation，用**跨表 `INSERT … SELECT … WHERE NOT EXISTS` 一条语句原子完成**（先查再插会与 takeover 竞态）。被拒时**必须抛错而非静默返回 False**——静默 False 会被调用方读成"副作用早已落地"，正好是最危险的误读；因此 `row is None` 后补一次 `has()` 判别，把「幂等去重」与「被 fence 拒绝」分开（仅 fenced 路径多这一次查询，`generation=None` 的旧路径逐字不变）。
  - 列由新迁移 `012_receipt_generation_fencing`（可回滚、`IF NOT EXISTS` 幂等）补齐。**刻意不改 `001_baseline.up.sql`**：已应用迁移的 checksum 被 `schema_migrations` 钉住，改动会让存量库启动即报 checksum mismatch。新建库跑完整链 001..012 同样得到两列 ⇒ 新库与升级库不分叉。
  - **残留（登记而不粉饰）**：① 真 PG 上的并发双写被拒**未验**（126 关机）⇒ 结构层用例只证「SQL 含 fence 子句 + generation 进参数 + DB 说没写进去时必抛」，行为层证明只在 InMemory 侧成立；② `PgAwaitableTaskStore` 双份定义未合并，`execution_state_pg.py:114` 那份仍无 fence（零生产调用，但它的 `save` 会把 generation 留空 ⇒ 若将来被接线，fence 会静默退化）；③ 进程内 side effect 后端**不做 fence**（无 lease 权威源、单进程也无 takeover），已在其 docstring 写明，不伪造"两后端语义对等"；④ `human_task.py:92` 构造 `AwaitableTask` 未盖 generation（该模块仍未接线，走 None 放行路径）。
- 项 2 打开后，`Rescheduler._retry` 会向队列新入一条请求 ⇒ **重试会消耗队列容量**，`QueueFull` 时重试静默失败（`execution_recovery.py:201-205` 只 warning）。默认关就是为此。
- 项 2 的 `contract_resolver` 本轮无生产实现可接（Effect Contract 由 planner 侧持有），默认 `None` ⇒ 决策退化为「无契约默认可重试」（`execution_recovery.py:135-136`）。这是**能力接上、语义待补**，不等于已按契约恢复。
- `PgAwaitableTaskStore` 双份定义本轮不合并，重复事实留在本行；`execution_state_pg.py:114` 那份仍无 fence，但它无生产调用点。
- 项 3 的 `recover` 复用 `execution_recovery`，因此它是「缺口 8」与「§3 execution_recovery 未接线」的共同收口点。
- 项 3 顺带补了一处**装配漏接**：`main.py` 构造 `ControlPlane` 时从未传 `awaitable_store`（形参一直存在），⇒ `inspect()` 的 `external_tasks` 段在生产恒为空。已补传，属缺口 8「inspect 不完整」的一部分。
- **项 5（exhibition skill_router）两截都已接上，且顺带堵掉一个旧漏洞**：
  - 门禁截（第一次提交）：`run_skill` 在 `skill.run` 之前调 `route()`，scope 不符 → `SCOPE_DENIED`、readiness SYNTHETIC → `DATA_NOT_CONNECTED`，两者 `warehouse.get_rest` 零调用。
  - 执行截（本次）：`route()` 解析出的 catalog `endpoint` 注入 `SkillContext.routed_endpoint`，skill 据此发请求；模块内硬编码的 `_REST_PATH` **已删** ⇒ `tool_catalog.json` 成为端点的唯一真相源（此前 catalog 与 skill 各持一份，漂移无人发现）。
  - **刻意选 fail-closed 而非硬编码兜底**：`routed_endpoint` 缺失时拒绝直连 warehouse（返回 `DATA_NOT_CONNECTED`，不发请求）。兜底会让门禁退化成"可绕过的建议"——直接调 `skill.run(...)` 就能跳过整条门禁链，这正是第一次提交时登记的残留漏洞；改成 fail-closed 后该路径结构性失效。代价是 6 处既有测试 fixture 必须补 `routed_endpoint=` 输入（**断言逐字未改**，只是补新契约要求的入参）。
  - **残留（不影响本项判定，但要写清）**：fail-closed 是**逐 skill 自觉取用** `routed_endpoint` 的结果，不是基类强制——新增 skill 若不读该字段，仍然可以直连 warehouse。要结构化就得把"取端点"收进 `BaseSkill`，属独立方案。
  - 一条测试自身的教训（记此防止复犯）：首版断言写 `"Skill Router" in result.answer` 而实跑为假——`_pending_result()` 把固定话术 `PENDING_ANSWER` 放 `answer`、把拒绝原因放 `warnings`。**产品行为是对的，错的是断言取错了字段**；改断言前先读被断言对象的构造，别按想象写。

## 6. 续批（2026-10-15 晚）：`payload_externalization` 接线 = 缺口 7

前 5 项落地后继续推 TODO 的未接线清单。选 `payload_externalization` 而非 `human_task` 的理由：它的两个入口 `externalize_completed()` / `internalize_completed()` 的签名就是 `dict[str, Any] -> dict[str, Any]`，**正好是 checkpoint `completed` 的形状**⇒ 接线点是唯一的、无需新抽象；而 `human_task` 需要一整套审批 API 面，属独立方案。

### 6.1 目标与影响面

| 项 | 内容 |
|---|---|
| 接线点 | `PgCheckpointStore.save()` 落库前 `externalize_completed()`；`load()` 读回后 `internalize_completed()` |
| 顺序硬约束 | `load()` 里**先 internalize 再 migrate**：schema 迁移函数按真实 payload 形状改写 `completed`，拿到 reference 会改错东西 |
| fencing 不受影响 | `externalize_completed` 保留 `node_id` 键 ⇒ `version = len(checkpoint.completed)` 不变，C3 monotonic CAS 与 generation fence 语义逐字不变 |
| 开关 | `PAYLOAD_EXTERNALIZATION_ENABLED`（默认 **False**）+ `PAYLOAD_EXTERNALIZATION_DIR` + `PAYLOAD_EXTERNALIZATION_THRESHOLD_BYTES`（默认 1MB，沿用 `ExternalizationConfig`） |
| 只接 PG 后端 | 缺口原文是「50MB JSON 直接塞 checkpoint **JSONB**」——问题只存在于 PG。无 DB 时走 `InMemoryCheckpointStore`，再套一层进程内 blob store 是自我矛盾，**刻意不接**（不是遗漏） |
| 联邦侧 | `applications/agent_federation/planners/__init__.py` 的 checkpoint store **不接**外部化（它没有对应的 dir 配置面）；登记在 §6.3，不静默 |

### 6.2 一个必须显式处理的降级面

`internalize()` 对**丢失的 blob** 原样返回 reference（模块注释写「供调用方处理」）。接线层若不处理，就是把「payload 没了」静默成「数据长这样」——正是本仓反复登记的那类静默降级。故 `load()` 在 internalize 后检测残值并 `logger.warning` 指名 execution 与 node 列表；**不抛错**（checkpoint 仍可用于判断进度，抛错会让恢复路径整体失败，代价大于收益）。为让接线层能识别残值，把模块私有的 `_is_reference` 提为公开 `is_reference` 并进 `__all__`（不是新增第二套判定）。

### 6.3 验收

1. `PgCheckpointStore` 带 externalizer：大 payload 落库后持久化 JSON 里是 reference（`__external__`）而非原值，blob store 里有原值；`load()` 往返还原相等。
2. 小 payload（低于阈值）**不**外部化。
3. blob 缺失 ⇒ `load()` 返回 reference 且**有 warning**（用 caplog 钉住，不接受"没抛错就算过"）。
4. `version` 等于原 `completed` 的键数（证明 fencing 未被外部化改变）；且既有 fencing 用例全绿。
5. 默认关 ⇒ `_externalizer is None`，行为与接线前逐字一致（装配层用例钉住）。
6. `PAYLOAD_EXTERNALIZATION_ENABLED=true` 但没给 dir ⇒ **启动即 RuntimeError**（沿用 `_build_pg_stores` 既有的 `db_enabled` fail-fast 先例），不静默降级成"没开"。
7. 全量门禁 rc=0 + 五个 pytest session 全绿；既有用例零删改。

**实跑结果（2026-10-15）**：判据 1–6 各有一条对应用例，落在 `tests/durability/test_payload_externalization_wiring.py`（9 条，用一个只模拟 `execution_checkpoints` 的替身池，断言对象是**真正落库的那份 JSON**）与 `applications/agent_server/tests/test_v3_wiring_assembly.py`（+3 条装配面）。全量：`ruff` / `check_doc_sync` / `lint_architecture` rc=0；pytest 根 **692 passed + 28 skipped**（683→692）、agent-runtime **631**、agent_server **105**（102→105）、联邦 **176**；`packages/agent-runtime/tests/test_payload_externalization.py` 原有 11 条未改未删仍全绿。判据 7 的"五个 session"里 exhibition 未受本批影响（357，上一批已跑）。
过程中被自己的用例抓到两处**断言写错**（非产品缺陷）：① `_build_pg_stores` 会自建 externalizer，断言 `is` 同一对象必假 ⇒ 改为断言类型；② 见 §6.2 提到的 `_is_reference` 改名漏了一处调用点（`_should_externalize`），会 NameError——**改名类改动必须全仓 grep 旧名，不能只靠编辑器式的批量替换命中一种写法**。

### 6.4 登记而不粉饰

- `FileSystemPayloadStore` 在**构造期**就 `os.makedirs`，所以开关一开即建目录；生产要换 S3/MinIO 适配器（同一 `PayloadStore` 契约），本轮不做。
- 外部化后的 blob **没有 retention/GC**：checkpoint 被覆盖或删除时旧 blob 变成孤儿，长期会堆积。属独立方案（需要 blob 侧的引用计数或按 execution 前缀清理）。
- blob 与 PG **不是一个事务**：写 blob 成功而 checkpoint 写入被 fence 拒绝时，blob 泄漏（同 §HA H3 登记的 side-effect 原子性问题同族，无法靠一条 SQL 修）。
- 联邦 planner 侧未接（见 §6.1 表末行）。
