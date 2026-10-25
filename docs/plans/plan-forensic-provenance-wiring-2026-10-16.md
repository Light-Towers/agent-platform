# 方案：把「数据来源 / 外部回执」接进取证记录（roadmap §四 第 6 条缺口）

**状态：** Proposed（**待拍板**，对应 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §3 第 19 项）。
**本文件不授权编码**：按 AGENTS.md 红线，批了才动 `forensic.py` / planner 执行链。
**创建于：** 2026-10-16 · **基线：** 分支 `chore/tech-debt-agentic-discovery-test-2026-10-15` tip `20382f1`。

---

## 1. 目标（一句话）

让"每次回答可追溯数据来源"从**载体在位**变成**字段真被填、且填了能查回来**：`ForensicContext` 的
`external_inputs` / `external_task_receipts` / `effect_receipts` 三格各获得一个生产写入点（A 层），并被 `divergence_diagnosis` 用起来；
同时补上持久化与读回（B 层，见 §1.1）——没有 B 层，A 层的产物只活在进程里。

**为什么现在只有三格空着**（实取，不是推测）：

| 取证层 | 现状 | 证据 |
|---|---|---|
| 逐步 `StepForensic` | **在写** | `planner/protocol.py:639` 构造，`:654/:717/:726` 挂到步骤、`:354` 挂到记录 |
| 记录级版本指纹 | **在写，但只 2 维** | `planner/execution_graph.py:58` = `ForensicContext(model=…, planner_version=…)`，全仓仅此一处生产构造 |
| 三格来源/回执 | **零写入点** | `git grep "external_inputs\|external_task_receipts\|effect_receipts"` 的非 tests 命中全在 `forensic.py` 自身（定义 / `to_dict` / `from_dict` / `divergence_diagnosis`） |
| 回执的真实落点 | 在**任务行**上，不在取证记录里 | `awaitable_task.py:158-159` `submission_receipt` / `completion_receipt`（fence 见 `68a44290`） |

⇒ 缺口性质是**两条链没接起来**：回执已经产生并可持久化，但每次回答的取证记录里没有它们的影子。

### 1.1 前置发现：记录级取证在 PG 部署下**根本没落库**（2026-10-16 实取，扩大了本方案范围）

写这份方案时我按"`store_pg.py` 未变 ⇒ 老行天然兼容"下笔，**那句话是错的**。用只读探针（伪连接捕获 SQL + 合成行回放 `_row_to_record`，本机可复现、无需真 PG）实取三条：

| # | 读数 | 证据（实跑，非推断） |
|---|---|---|
| ① | `PgTrajectoryStore` 全类 `forensic` 命中 **0 次**；INSERT 列表只有 `execution_id, parent_execution_id, session_id, planner, plan, steps, total_tokens, total_cost, snapshot, created_at` | `trajectory/store_pg.py:48-79` 捕获到的 SQL；表 DDL `migrations/001_baseline.up.sql:173-184` 同样无 forensic 列 |
| ② | 带 `forensic` 的记录 save 后 get 回来 `record.forensic is None` ⇒ **记录级取证在 PG 侧整片丢失**（`InMemoryTrajectoryStore` 因存对象本身而保留） | 探针读数 D) |
| ③ | 读回的 `steps` 元素类型是 `dict` 而非 `TrajectoryStep`，`steps[0].name` 抛 `AttributeError`；`_coerce_record`（`store.py:61-88`）既不恢复记录级 `forensic`，也不给 step 传 `forensic=` | 探针读数 D) + `store_pg.py:105-129`（`_row_to_record` 自有一条路径，没复用 `_coerce_record`） |

**这条发现的边界（防被过度读）**：
- step 级取证**在 PG 里没丢**——它随 `s.to_dict()` 序列化进 `steps` JSONB，只是读回后只能 `["forensic"]` 取、不能 `.forensic` 取。
- "replay 从 PG 读会 `AttributeError`"目前是**潜伏缺陷，不是现网故障**：`replay_trajectory` / `build_replay_registry` 经 `git grep` 核对**零生产调用方**（命中只在 `packages/agent-runtime/tests/test_replay.py` 与包 `__init__` 导出）。
- `tenant_id` 不在 DDL 里**是已登记的设计选择**，不是新缺口：`tests/governance/test_isolation_dimension_contract.py:40` 把 `trajectories` 列入无租户表白名单，`scripts/audit_tenant_access.py:233` 探测不到租户列即 `skip`。但白名单给的理由写的是"按 execution_id 定位（可观测/**回放**）"——③ 说明这个"回放"在 PG 读路径上并不成立，理由句需要随本方案一起订正。
- 与 `docs/operations/minimal-release-runbook.md` §8 第 2 条的关系：那条已经禁止讲"历史调用档案可查"（理由：默认执行路径不写档案表）。本文补**第二条独立理由**：即使写了表，记录级取证也会被丢。

⇒ 本方案因此有**两层**，不是原来写的一层：**A 字段填充**（三格有生产写入点）与 **B 持久化与读回**（列/迁移 + `save` 带出 + `_row_to_record` 走 `_coerce_record`）。**只做 A 在 PG 部署下等于没做**——填好的 dict 依然落不进库。

## 2. 影响面

- **改动点**：`planner/execution_graph.py::_persist_trajectory`（唯一记录装配点）；`effect_contract.py` / `awaitable_task.py` 的回执出口（只读取出，不改其语义）；工具执行侧若要登记 `external_inputs`，落点在 `protocol.py` 已构造 `StepForensic` 的同一处。**B 层另需改 `trajectory/store_pg.py`（save 带出 forensic + `_row_to_record` 收敛到 `_coerce_record`）与 `trajectory/store.py::_coerce_record`（恢复 forensic，step 级也要）**。
- **数据结构 / 迁移（订正：本节初稿写错，正确读数见 §1.1）**：`TrajectoryRecord.forensic` 只存在于内存与 `to_dict()`；**PG 表根本没有该列**（`001_baseline.up.sql:173-184`），`save` 也不发它 ⇒ "无需 DB 迁移"这句不成立。B 层要做一次**加列迁移**（`forensic JSONB NOT NULL DEFAULT '{}'`，或按 Q5 选择嵌进 `snapshot`），并让 `get`/`list_by_session` 读回后仍可用属性访问 steps。老行兼容仍成立，但**兼容点在"读回缺省为空"，不在"不用改存储"**。
- **下游**：`/health` 的 `forensic` 位不变（它取的是 `trajectory_store` 装配态，`health_router.py:50`，语义已在 `schemas.py` 声明）⇒ 响应键数 25 不动。`divergence_diagnosis` 已把这三部 dict 当比较面（`forensic.py:160`），填上后**回放比对会开始报出以前报不出的差异**——这是目的，也是行为变化点。
- **不在范围内**：不改任何对外 API 形状；不改 `DEPLOY_ENFORCE_IDENTITY`；不动 KS/exhibition 自己的 `citations`（那是业务侧返回体，不是平台取证面）。

## 3. 五个必须先定的问题（每题给选项 + 我的推荐，但不替你决定）

**Q1 粒度**：每次外部调用一条（`source → hash` 逐项），还是每次回答汇总一条？
a 逐调用（diff 能力最强，体积随步数增长）/ b 回答级汇总（体积小，定位不到"哪一步换了数据源"）。
推荐 a，理由：`divergence_diagnosis` 的既有实现就是按 dict 键比对，b 会让它退化成"只比整体"。

**Q2 哈希口径**：原文 sha256 / 引用 ID（如 warehouse 返回的 `record_id`）/ 长度+前缀？
推荐 **优先引用 ID，无 ID 时落 `sha256:` 前 12 位**，且 dict 里同时记 `kind`（`ref|hash`）——
理由：回放时能判断"当时取的是哪条记录"比"当时那串字节长什么样"有用；纯 hash 无法反查，纯原文会踩 PII。
**这条需要你定**：是否允许在无 ID 时保留 12 位前缀（它泄露极少量内容特征）。

**Q3 PII 与数据分级边界**：会展链路含客户线索（lead），KS 有业务语料。哪些 tier 的外部输入允许进 `external_inputs`？
a 只允许标识类（ID/URL/时间戳）/ b 允许非 PII 字段名列表（需一份 allowlist）/ c 全部按 hash 落（内容特征不外泄但仍可能反查）。
推荐 a 起步（b 需要业务方给字段清单，我没有）。

**Q4 回执汇流方向**：`awaitable_task` 的 receipt 是否单向抄进 `ForensicContext.external_task_receipts`？
推荐 是（只读抄录，任务行仍是真相源），但**必须定失败语义**：抄录失败要不要阻断执行？推荐**不阻断、记 warning**，
理由：取证面是事后诊断用，阻断会让可观测性缺陷升级成可用性事故。

**Q5 持久化落点（B 层，由 §1.1 新暴露，必须定）**：记录级 forensic 怎么进库？
a 加独立列 `forensic JSONB NOT NULL DEFAULT '{}'`（要一条新迁移；`runner.py:45` 的表清单与 `test_isolation_dimension_contract.py` 的存在性口径都要跟着确认）/
b 嵌进已有的 `snapshot` JSONB（零迁移、零 DDL 变更，但 forensic 不再是可单独查询/加索引的字段，且 snapshot 语义会被两种用途混用）/
c 什么都不做，只在文档里承认"取证面只在进程内可见"（roadmap §四 第 6 条就按"未达标"记）。
推荐 **a**，理由：第 6 条要的判据是"每次回答可追溯"，"可追溯"必须能在库里按 execution_id 查回来；b 会让下一轮想按维度筛（比如列出所有用了某模型版本的执行）时又得回到 a。c 只在你想把第 6 条整体后置到阶段 3 时才成立。
**注意 a 的连带项**：`_row_to_record` 必须改为复用 `_coerce_record`（否则 ③ 的类型断裂仍在，replay 从库里读依然崩），且 `_coerce_record` 本身要先补 forensic 恢复——这两处不补，加了列也读不回来。

## 4. 迁移策略

1. 纯新增，不改读法：三格继续可选，未登记的 source 不进 dict ⇒ 老行为零变化。
2. 开关：`FORENSIC_EXTERNAL_INPUTS`（默认值随 Q3 的选择定；建议默认 `off` 一个版本、灰度到 `on`），
   与既有 `DEPLOY_ENFORCE_IDENTITY` / `TENANT_JWT_ENFORCE` 的"渐进开启"同形态，**登记进根 `.env.example`**（那里已有齐全性门禁 `tests/governance/test_agent_server_env_template.py`，新键漏登记会直接报红）。
3. 分三步提交：**B 层（Q5 落列 + 修 `save`/`_coerce_record`/`_row_to_record` 读回）先行**，因为它独立于所有争议且是后两步的前提——B 不修，A 填的字段永远进不了库；随后**第一步做 Q4**（回执抄录，落点最少、争议最小）；最后**第二步做 Q1–Q3** 的 `external_inputs`。
4. B 层的迁移是**加列、不改已有列语义**，老行按缺省空 dict 读回 ⇒ 无需回填历史数据（历史本来就没存，回填不了，这一点要在文档里写明，不能让人以为补了列就有了历史档案）。

## 5. 验收标准（"做完"的可核对定义）

| 判据 | 怎么验 |
|---|---|
| 三格各有一个**生产写入点** | `git grep -n "external_inputs\s*=\|external_task_receipts\s*=\|effect_receipts\s*=" -- '*.py'` 的非 tests 命中数 ≥ 1/格 |
| 「输入变则值变」 | 新增用例：同一 plan 两次执行，外部输入 hash 不同 ⇒ `divergence_diagnosis` 必须报出该维度差异；回执缺一条 ⇒ 必须报差异 |
| **【B 层】forensic 真进 INSERT** | 本机即可测（不需要真 PG）：用伪连接捕获 `save` 的 SQL 与绑定参数 ⇒ 列清单含 `forensic`、参数里含该 dict。这条就是 §1.1 探针的做法，把它固化成用例 |
| **【B 层】读回类型不破** | 伪行喂 `_row_to_record` ⇒ `steps[0]` 必须是 `TrajectoryStep`（属性可访问）、`record.forensic` 必须非 None；另加一条 `replay_trajectory(从库读回的 record)` 不抛 `AttributeError` |
| **【B 层】老行兼容** | `forensic` 列为 SQL `NULL`/缺省 `{}` 的行读回 ⇒ `ForensicContext.from_dict({})` 得全空指纹，不抛异常 |
| 老行兼容（A 层字段面） | 用不含三格的旧 `forensic` dict 走 `from_dict` ⇒ 得空 dict，不抛异常 |
| 真 PG 端到端 | **待环境**：加 `@pytest.mark.requires_pg` 的 round-trip 用例（缺 PG 自动 skip 属设计意图，不得当作已验） |
| 不动对外面 | `/health` 响应仍 25 键；`test_health_fields.py` 全绿；根 session 无回归 |
| 非空转反证 | 至少 4 条变异：摘掉写入点 / 改掉 hash / 让抄录失败 / **把 `save` 的 forensic 参数改回 None**，各自必须报红（照 `docs/operations/evidence-format.md` §4 的表式交，并区分 `rc=1` 断言触发 vs `rc=4` 探针坏了） |
| 默认值与开关 | 新键进根模板；开关关时行为与本批前一致（差分用例） |

## 6. 工时与排期（等拍板后才生效）

- **B 层（Q5 落列 + 三处读回修复 + 上面四条 B 判据的用例）：1 人/日**（含一条新迁移与 `runner.py` 表清单核对）。
- 第一步（Q4 回执抄录 + 用例）：0.5 人/日；第二步（Q1–Q3 + `external_inputs` + allowlist）：1.5 人/日。合计 **3 人/日**。
- **建议截止**：拍板后 2 个工作日内完成 B 层 + 第一步；全部落在 roadmap 阶段 2 窗口（10/31–11/13）内，
  以便 §四 第 6 条在 11/13 前从「部分达标」回到「可判定」。若选 §3 第 19 项的 b（后置到阶段 3），则本文件只登记不动工。
- **排期硬约束（新）**：第 6 条在 B 层完成前**不可能翻绿**——字段填了也查不回来。所以若你想在 11/13 判定第 6 条，B 层不能砍。
