# 会话回退完整性方案：checkpoint id 与「有没有历史点可退」

**版本：** V1
**状态：** **Proposed（待拍板）**——本文只做定夺与排期，未改一行产品代码。
**证据件：** `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/readings.md`（四支可复跑探针 + 读数；本文不重复贴读数，只引用其结论编号 A / B1 / B2 / C）。
**判据对象：** `docs/plans/plan-web-frontend-minimal-core-2026-10-29.md` §7 工单 **PR-3**（会话历史 + `/session/revert` 交互）的开工前置。
**为什么单开一份：** PR-3 原报告只写了「`checkpoint_id` 取不到」。实测证明那只是三层问题里最表层的一层，
且**另两层决定 PR-3 该不该按原设计做**。按 AGENTS.md《先方案后代码》，这属于必须先记录定夺的技术方案。

---

## 1. 问题陈述（一句话一条，编号供后文引用）

| # | 事实 | 来源 |
|---|---|---|
| **A** | Planner 主路径每线程**恒只有一条 checkpoint**（`append_thread` 复用读侧最新行的 id 原地覆写），**没有任何历史点可回退** | 探针 A；成因 `applications/agent_server/memory/thread_persist.py:82-84` + `:116` |
| **B1** | `revert.py` 用随机 `uuid.uuid4()` 作新行 id，而读侧按**字典序**判最新 ⇒ 掷硬币：**返回 `success=True` 而状态未变**（两轮 n=60 抽样 8.3% / 13.3%，理论值 12.15%） | 探针 B 两轮 n=120；成因 `packages/agent-runtime/agent_runtime/revert.py:77` |
| **B2** | 反方向更重：那条**赢了**字典序的 uuid4 行会**永久遮蔽**此后每一行按 uuid6 写入的 checkpoint ⇒ 线程冻结在回退点（实测 3/3 轮全灭，且双自检确认行确实落库） | 探针 D |
| **C** | 回退产生的新行 id 不对外（`RevertResult.checkpoint_id` 返回的是**目标 id**，`revert.py:109-114`），且 `/history` **根本不列举 checkpoint**（只读最新一条，`recall_exact.py:70-75`；`HistoryItem.id` 是消息 id，`:45`）⇒ **接口面**无任何可取 checkpoint id 的出口（取证 rev `896f966e`：`git grep -I -n -F -e checkpoint_id -- applications/ packages/` = **77 行 / 10 文件**，其中作为 HTTP 响应/请求字段出现的只有 `applications/agent_server/api/session_router.py` 的 :78（入参，客户端得先知道 id）与 :91（响应，而它回填的就是本行说的目标 id）；余下 75 行全在存储层/清理器/测试。两处引用坐标已逐条核到盘：`recall_exact.py` 实路径 `applications/agent_server/memory/recall_exact.py`，:70-75 确为 `aget_tuple` 只取最新一条、:45 确为 `"id": getattr(msg, "id", None)`；`revert.py` = `packages/agent-runtime/agent_runtime/revert.py`，:109-114 确为 `RevertResult(...)` 回填 | 探针 A §3 + 源码（引用坐标 2026-10-29 复核） |
| **D** | 三处读侧表达式**同构**，都是字典序取最大：`InMemorySaver.get_tuple` 用 `max(keys)`、`AsyncPostgresSaver` 用 `ORDER BY checkpoint_id DESC`（列类型 `TEXT`）、本仓 `MongoCheckpointer.alist` 用 `.sort("checkpoint_id", -1)` ⇒ 不是内存态专属问题 | 探针 C |
| **E** | 「A 掩盖 B」：今天 B 不发作，正因为 `append_thread` 继承遮蔽行自己的 id 继续原地覆写。**一旦让每轮产生新 id，B 立刻发作** ⇒ A 与 B 不是独立缺口 | 探针 D + `thread_persist.py:82-84` |
| **F** | 当前在册测试拦不住：`packages/agent-runtime/tests/test_revert.py` 播种 id 是字面量 `"cp1"`（非 UUID，走不到排序关系），且 `test_revert_creates_new_checkpoint_id` 只断言「目标行未被覆写」，**从不断言新行成为读侧最新态** ⇒ 断言面窄于契约 | `:32-48`、`:87-94` |

**还有一条与承诺相关的：** `applications/agent_server/config.py:88` 是 `revert_enabled: bool = True`（**默认开**），
而 `README.md:272-279` 对外承诺「回退至指定 checkpoint，不删除历史（支持 redo）」。
按 A 的读数，**这条承诺今天任何时刻都不成立**（没有历史点，回退必然退到"当前态"自己）。
⇒ 这不是 A/B/C 的实现问题，而是**对外陈述与现场不符**，属 AGENTS.md 红线「不把'接线'当'启用'」的同族。

---

## 2. 目标与非目标

**目标**
1. 让 `/session/revert` 有**可核对的语义**：要么真能回退到历史点，要么明确告知「本会话没有历史点」。不再出现 `success=True` 而状态未变。
2. 消除 id 排序依赖带来的静默失效（B1）与永久遮蔽（B2），包括对**存量已回退线程**的处置结论。
3. 给 PR-3 一个**可开工的前置答案**：前端从哪个接口拿到回退目标。
4. 让回归测试的断言面**覆盖到契约本身**（读侧最新态），并给非空转反证表。

**非目标**
- 不改多租户/归属断言（G3/T1.2 已接线，`session_router.py:63-77` + `revert.py:44-52` + 在册 403 用例）。
- 不做前端交互（属 PR-3 本体，须先过本方案）。
- 不引入新框架、不为「排序 id」新增第三方依赖。
- 不动 `checkpoint_cleaner.py` 的清理算法（只在选 A1 时确认它是否覆盖 agent_server，见 §5）。

---

## 3. 影响面（逐项，不打包）

| 面 | 具体位置 | 说明 |
|---|---|---|
| 产品代码 | `packages/agent-runtime/agent_runtime/revert.py:73-90`（mint + aput）、`:109-114`（返回目标 id）、`:1-7`（docstring 承诺）、`:23`（构造签名） | 唯一 mint 新 checkpoint 行的地方 |
| 产品代码 | `applications/agent_server/memory/thread_persist.py:82-84,116` | A 的成因；选 A1 则此处改为产生新行 |
| 装配点 | `applications/agent_server/main.py:377-381`（`if settings.revert_enabled:` 内 `RevertHandler(checkpointer, pool)`） | 全仓**唯一**生产装配点（`git grep "RevertHandler("` 实测共 3 处：此处 + 2 处测试） |
| 契约 | `applications/agent_server/schemas.py:186-195`（`RevertRequest`/`RevertResponse`）、`:199-203`（`HistoryItem`）；`README.md:272-279` | 对外形状与承诺文案 |
| 依赖方向 | `packages/agent-runtime/pyproject.toml` 依赖仅 `agent-core / shared-schemas / pydantic / pydantic-settings / valkey`，**包内零 `from langgraph` import** | 时序 id 生成器 `langgraph.checkpoint.base.id.uuid6` 不在该包依赖面内。**注意有个同族先例**：`agent-core` 在 `get_checkpointer` 里**懒导入** langgraph（`:87`、`:115`）并配了 `memory-pgvector` 可选 extra ⇒ 所以"不能引"不是铁律，而是"agent-runtime 至今一刀未开且声明为协议中立"；要开口就走懒导入 + 可选 extra，那是一次**依赖面变更**（属架构决定，本文不预设） |
| 存储/retention | `applications/agent_federation/agent/checkpoint_cleaner.py:24,26`（默认 `CHECKPOINT_KEEP_PER_THREAD=5`、`CHECKPOINT_RETENTION_HOURS=6`）；启动点**只在** `applications/agent_federation/api/server.py:109` | ⇒ **agent_server 侧没有任何 checkpoint 清理器**。选 A1（每轮累积）等于引入无上限存储增长 |
| 在册测试 | `packages/agent-runtime/tests/test_revert.py`（`:24-25` fixture 构造）、`applications/agent_server/tests/test_history_real_checkpointer.py:171-211`（HTTP 层归属）、`tests/governance/test_audit_operator_principal.py:140`（构造 handler） | 改构造签名会同时命中这 3 处 |
| 审计 | `revert_audit` 表（`revert.py:147-163`，字段 `source_checkpoint_id` / `target_checkpoint_id`） | 语义随所选方案变化，须一并订正 |

---

## 4. 决策：A 的三种形状（这是唯一需要人拍板的地方）

三条都能"让回退可用"，代价差别很大。**共同前提**：无论选哪条，`success=True 但状态未变` 必须先变成显式失败（见 §4.0）。

### 4.0 步骤 0（不依赖 A 的选择，先止血）— D1
- revert 前置检查：该线程 `alist` 条数 ≤ 1 且目标 == 最新态 ⇒ 返回 `NO_CHECKPOINT_HISTORY`（HTTP 409），**不再谎报 success**。
- 同步订正 `README.md:272-279` 的承诺文案与 `config.py:88` 默认值：**默认开着一个当前无能力支撑的写接口 = 对外承诺了不存在的能力**。建议 `revert_enabled` 默认改 `False`，待所选形状落地后再开。
- 这两条各 < 60 行，无依赖、无迁移。

### 4.1 选 A1：真·checkpoint 级（保持现有契约与承诺）
每轮 `append_thread` **产生新行**（时序 id），历史点真实存在，`不删除历史（支持 redo）` 承诺成立。
必带四项，缺一不可：
1. **id 注入**：`RevertHandler` 与 `append_thread` 的新行 id 由**应用层注入的工厂**提供（装配点 `main.py:379` 传 `lambda: str(uuid6())`，取自 `langgraph.checkpoint.base.id`）。
   agent-runtime 内**不得**出现 `from langgraph`（依赖方向红线）；探针 C 实测 `uuid6()` 连调 1000 个**严格递增且无重复**，故注入式既保依赖方向又保排序。
2. **存量处置**：已发生回退的线程里存着 uuid4 行（首 4 位十六进制均匀分布，绝大多数 > 当前 v6 前缀）⇒ 按 B2，这些线程一旦开始产生 v6 新行就**永久冻结**。必须先把它们**改写为同线程内的时序等价 id**（或标记并丢弃这些线程的历史）。清点语句形状：按 `metadata->>'reverted_from' IS NOT NULL` 且 `checkpoint_id` 非 v6 族逐线程取 max。
   ⚠ 本仓**没有**跑过 PG/Mongo 实盘 ⇒ 存量规模是未知数，这是选 A1 的**先决取证项**，不得跳过。
3. **retention**：agent_server 侧必须接清理器（现只在 federation 启动），否则每轮累积 = 无上限增长。
4. **端点**：新增「列举本线程可回退点」的读接口（C 的唯一解；`/history` 与 SSE 都不带 id，见 §1-C）。新增端点是**纯增量**（`console.html` 不调 revert，`web/` 尚不存在 ⇒ 现网无消费者），但须按 AGENTS.md《边界》先做消费者审计并把结论写回。

代价：跨包签名变更 + 数据迁移 + 新端点 + 新 retention 接线。**4 个不可逆/高影响项**，属 D2。

### 4.2 选 A3：轮次锚点，**不产生新行**（推荐）
把「回退目标」从 LangGraph 的行主键降级为**应用层的轮次记号**：
`append_thread` 每轮在 `channel_values` 里追加一条锚点 `{token, message_count, ts}`（沿用同文件 `:107-112` `task_snapshot` 通道的既有姿势，不是新发明），
`revert` = 读最新行 → 把 `messages` 截到锚点 `message_count` → **原地覆写同一行（id 不变）**。
于是：
- **B1/B2 一起消失**：不 mint 行 id ⇒ 无排序依赖 ⇒ 无需 id 工厂、**无需存量迁移**、无需碰依赖方向。
- **C 自动解决**：`/history` 的每条回复可带该轮 `token`（**可选字段，纯增量**），前端拿它当 `checkpoint_id` 传回 ⇒ 不加端点。
- **A 的真实需求满足**：用户心智里的"回退"本来就是"退回第 N 轮"。
- **无存储增长** ⇒ 不需要 retention 接线。
代价（必须诚实订正，这是本选项的主要成本）：
- 放弃 `不删除历史 checkpoint（支持 redo）`（`revert.py:4` docstring + `README.md:279`）⇒ 回退后**退不回去**，`revert_audit.source_checkpoint_id` 语义改为"被截断到的锚点"。
- `RevertRequest.checkpoint_id` 字段名保留但**含义变更**（应用层记号 ≠ LangGraph 行主键）。字段形状不变 ⇒ 不破坏任何按形状解析的代码；但文档必须改写清楚，否则是**语义漂移**（比形状破坏更坏，因为它不报错）。

### 4.3 否决项（都留了证据，别复议）
| 候选 | 否决理由 |
|---|---|
| 把 `uuid4` 换成 `uuid_utils.uuid7()` | **实测必败**：探针 C 里 v7 的 `01a1…` 字典序**恒小于** LangGraph v6 的 `1f1d…` ⇒ 换完是"每一次回退都静默失效"，比掷硬币更糟。直觉上的"可排序 id"与"能赢过既有族"是两件事。 |
| 在 agent-runtime 直接 `from langgraph.checkpoint.base.id import uuid6` | 违反红线 1 与该包刻意的协议中立（实测 `pyproject.toml` 无 langgraph、包内零 `from langgraph`），且 A3 下根本不需要。 |
| 只给 `HistoryItem` 加 `checkpoint_id` 字段 | 治不了本：行只有一条（A），加了字段也只有一个值 = 当前态；且若未来选 A1，字段值仍是"目标 id"（C 未修）。 |
| 先修 A 再说 B | 被 B2 直接否证：修完 A 的那一刻，所有历史回退线程冻结。 |
| 手写时序 id（不注入、不引 langgraph） | 要自证"永远赢过 LangGraph 自己的 v6 前缀"，等于把排序不变量从框架手里接过来自已维护 ⇒ 适配成本 > 收益，按《框架选型规则》应复用框架的 `create_checkpoint` 同族 id。 |

---

## 5. 迁移策略（按所选形状分期；每期一个可独立验证的 PR）

| 期 | 内容 | 形状无关？ | 规模 |
|---|---|---|---|
| **P-0** | §4.0 止血（`NO_CHECKPOINT_HISTORY` + 承诺文案 + `revert_enabled` 默认值） | ✅ 无关 | <60 行 |
| **P-1** | 决策落地。A3：锚点写入 + 截断覆写 + `/history` 可选 `token` + docstring/README 语义订正；A1：id 注入 + 存量迁移脚本 + retention 接线 + 列举端点 | — | A3 ≈250 行 / A1 ≈600 行（须再拆） |
| **P-2** | 回归测试补断言面（§6）+ 非空转反证 | ✅ | <150 行 |
| **P-3** | PR-3 前端交互开工（`web/`，不在本文范围） | — | — |

**灰度与回滚**：A3 不产生新行、不改数据 ⇒ 回滚 = 回退代码；A1 含数据迁移 ⇒ **迁移必须可重入且不可逆**，所以必须先在 126 环境取存量规模读数，再决定是否值得做（D2 前置）。

---

## 6. 验收标准（含"断言能红"的反证）

**功能判据（按 A3 写；A1 需把第 2、3 条替换为"列举端点返回 ≥2 个可回退点"）**
1. 连续两轮 `/query` 后调 `/session/revert` 带第 1 轮的 token ⇒ `/history` 只剩第 1 轮内容，**且读侧最新态就是回退结果**（不是只看 HTTP 200）。
2. 同一线程回退后再问一轮 ⇒ `/history` 含"回退点 + 新一轮"（证明截断后仍可继续写）。
3. 对一个从未回退过的历史线程（含线上存量 uuid4 行线程）调用 ⇒ 行为正确、且读侧**不冻结**（A3 的对照证据）。
4. `revert_enabled=False` 时 ⇒ 404 `REVERT_NOT_ENABLED`（既有分支，不许回归）。
5. `README.md` 与 `revert.py` docstring 的承诺与现场一致：要么真支持 redo（A1），要么显式声明"不支持 redo"（A3）。**留一条错话就是下一次的取证陷阱**——本会话刚在选型文档抓到同族问题。

**测试面（必须做到"断言面 == 契约"）**
- 播种 id 不再用字面量 `"cp1"`，改用**产品同款时序 id** 与**故意偏小的 id** 两组。
- 新增断言：`revert` 后 `aget_tuple` 无 id 分支读回的 id **就是**本次写入行（A1）/ 读回的 messages 内容 == 截断后内容（A3）。
- **禁止**为过测试而放宽：不许把"读侧最新态"断言降回"目标行未被覆写"。

**非空转反证表（AGENTS.md 新门禁口径，`docs/operations/evidence-format.md` §4）**

| 变异 | 期望 |
|---|---|
| A3：把截断锚点查询改成返回空列表 | 用例 1 报红 |
| A3：把 `message_count` 改成 `+1`（多留一条） | 用例 1 报红（断言的是精确内容，不是长度>0） |
| A1：把注入工厂换成 `uuid4` | 用例「新行成为最新态」在**固定小 id 正控**下报红 |
| A1：给工厂注入**故意偏小**的 id | 断言「新行成为最新」必须为 False ⇒ 证明这条断言真的能红（不是恒真） |
| 删掉 `NO_CHECKPOINT_HISTORY` 前置检查 | P-0 用例报红 |

---

## 7. 待拍板清单（全部 D2，逐条给建议但不代答）

| # | 待决 | 我的建议 | 不做的后果 |
|---|---|---|---|
| 1 | A1 还是 A3 | **A3** | 选 A1 = 数据迁移 + 无上限存储 + 新端点 + 跨包依赖治理四件事一起上身 |
| 2 | `revert_enabled` 默认值 True→False | 改 False | 默认对外承诺一个当前不成立的能力 |
| 3 | 「不删除历史（支持 redo）」承诺是否放弃 | 随 #1；若坚持保留则只能选 A1 | README 继续留着错话 |
| 4 | 若选 A1：存量 uuid4 行的处置口径 | 先上 126 取读数再定 | 部分线程冻结，且现场不可解释 |
| 5 | 若选 A1：agent_server 侧 retention 接线 | 与 A1 同批，不许后补 | 无上限增长 |
| 6 | `docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md:73`（G3）与 `README.md:67` 那条「跨用户回退未被禁止」的**过期警示**（代码与在册用例已实现 FORBIDDEN/403） | 顺手订正为"已接线"并保留成因 | 反过来误导：把已有能力当缺口重复实现 |

> #6 是本轮读码顺带撞见的：`README.md:67` 断言"跨用户回退目前并未被禁止……FORBIDDEN 是死码"，
> 而 `session_router.py:63-77` + `revert.py:44-52` + `test_history_real_checkpointer.py:193-201`（403 用例）
> + `test_revert.py:151-155` 证明它已接线。方向上是"少报能力"，安全侧，但仍是错话。

---

## 8. 未证与边界（诚实标注）

- **PG / Mongo 态未实跑**：§1-D 那两条读侧表达式是 langgraph `1.2.16` **源码读出**；`B2` 的遮蔽与存量规模在真库上未验证 ⇒ 任何"线上有 N 个线程被污染"的数字本文一个都不给。
- **agent_server 生产 checkpointer 形态**：工厂 `packages/agent-core/agent_core/memory/__init__.py:67` 的优先级是
  `pg_pool` ⇒ `MONGO_URL` ⇒ `InMemorySaver`（docstring `:70-78`，**生产推荐是 Mongo**）。
  本方案所有读数取自 `InMemorySaver`；而 Mongo 态的读侧表达式是**本仓自研**的 `MongoCheckpointer`（与 PG 同为字典序），
  所以选 A1 前必须在 **PG 与 Mongo 两种态各复跑一次探针 B/D**（尤其 Mongo：它是行内 blob 的自己实现）。
- **`checkpoint_cleaner` 与读侧的一致性**：两者用同一条字典序规则，所以"清理器删错方向"只能表述为「相对**写入时间**删错」（`readings.md` §0 已按此口径写），不得夸大成"两者互相打架"。
- 本方案不覆盖 federation 侧 `get_main_checkpointer()` 的 id 族（只确认它是清理器的作用对象）；若选 A1，须另行确认 federation 写入者是否也 mint id ⇒ 那会扩大影响面，需二次评估。

---

## 9. 落地后要回填的文档（不许只改代码）

| 文档 | 要改什么 |
|---|---|
| `docs/plans/plan-web-frontend-minimal-core-2026-10-29.md` §7 PR-3 行 + §11.5 | 开工前置由「checkpoint_id 取不到」改为「本文决策 #1 已定 + P-0/P-1 已完成」；同批必 add 清单加本文与证据件 |
| `packages/agent-runtime/agent_runtime/revert.py` docstring | 与所选形状的承诺对齐（redo 有无、id 语义） |
| `README.md:272-279` + `:67` | revert 段语义订正 + §7-#6 过期警示订正 |
| `docs/operations/minimal-release-runbook.md:216,239` | 若 `revert_enabled` 默认值改变，"无密钥 401" 那两条的覆盖面要重取 |
| 新建 ADR（**仅当选 A1**） | 「Runtime 侧 id 生成由应用层注入」属架构性 + 难逆（含数据迁移），够 ADR 门槛；选 A3 不开 ADR，本文即记录 |
