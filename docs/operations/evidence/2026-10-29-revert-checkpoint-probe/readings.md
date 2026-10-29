# revert / checkpoint 完整性取证读数（2026-10-29）

**定位：** 证据记录（不是方案）。格式遵循 `docs/operations/evidence-format.md` §1 五字段 + §3 强度分档。
**服务对象：** `docs/plans/plan-web-frontend-minimal-core-2026-10-29.md` 工单 **PR-3**（`checkpoint_id` 对外可得）
的**开工前置**——查证中发现 PR-3 的原缺口只是三层问题里最表层的，本文件记录另外两层的实测读数。
**方案文档：** `docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md`。

---

## 0. 结论与档位（先看这里）

四个读数，分属**三个缺口**（A / B / C）。它们不是并列的：
**A 正在用它的"无害"掩盖 B**（机制见下一段）；C 是 PR-3 原报告里那个表层缺口。

| 缺口 | 一句话 | 实测档位 |
|---|---|---|
| **A 无历史点** | Planner 主路径每线程**恒只有一条 checkpoint**（原地覆写），没有任何可回退点 | 本机实跑（InMemorySaver） |
| **B1 id 竞态** | `revert.py` 用随机 uuid4 作新行 id，与读侧"字典序即最新"的假设**掷硬币**：**静默失效**（`success=True` 但状态未变），两轮 n=60 抽样得 8.3% / 13.3%，理论值 12.15% | 本机实跑两轮 n=120 |
| **B2 遮蔽冻结** | 反方向更重：赢了字典序的那条 uuid4 行会**永久遮蔽**后续按 uuid6 写入的每一行⇒线程冻结在回退点 | 本机实跑（探针 D） |
| **C id 不可得** | 新行 id 不对外（`RevertResult.checkpoint_id` 是**目标 id**），且 `/history` **根本不列举 checkpoint** ⇒ 无任何接口可取 id | 源码读出 + 探针 A 第 3 节印证 |

**A 与 B 的叠乘关系**（这是本取证最重要的一条结论，不是几条并列事实）：
A 让"回退"当前是**语义空操作**（目标只能是自己）；一旦按 PR-3 修好 A 让 checkpoint 真正累积，
**B 立刻接管**，而且两个方向都坏：
- 约 8%–13% 的回退返回 `success=True` 而状态没变（B1，两轮抽样 5/60 与 8/60）；
- 其余（赢了字典序的那批）更重——那条 uuid4 行会让**此后每一次写入全部读不到**（B2）。
  探针 D 实测：3/3 轮均"行已落地但读侧不认"，线程永久冻结在回退点。
⇒ **B 是 A 的硬前置，且修 B 同批必须处置存量 uuid4 行**（否则存量数据会毒化新开光的累积写入）。
今天为什么没暴露：`append_thread` 复用"读侧最新行"的 id 原地覆写，连带把回退行继承了下去——
**它是靠缺口 A 在掩盖缺口 B**，两个缺口不是独立的。

同族影响（方向说清，不含夸大）：retention 清理器与读侧用的是**同一条字典序规则**，
所以两者彼此一致；不一致的是它们与**写入时间**。后果：B1 那一类回退行（uuid4 字典序小于目标）
既在读侧隐身，又排在清理器保留窗口的**最下方⇒最先被删**，等于把"发生过一次回退"的痕迹
按审计记录（`revert_audit` 仍写了 success）与现场状态**分开两套账**。

**未证部分（第三档，不承诺日期）**：PG / Mongo 两种生产态 saver 的"最新"表达式与列类型是
**从安装在本机的 langgraph 源码读出的**，未起库实跑；清理器的删错方向为**同式推论**，未实跑。

---

## 1. 五个必填字段

**① 代码版本**：rev `896f966e`（分支 `feat/nl2sql-ttl-and-006-slim`）。
读数绑定 `packages/agent-runtime/agent_runtime/revert.py`、`applications/agent_server/memory/thread_persist.py`
的产品代码，本批**未改一行产品代码**——反证：`git diff --stat -- applications packages` 输出为空（字段② 末条命令）。

**② 执行命令**（原样可复制；Windows PowerShell 实跑形式，三支探针均已入库本目录）：

```powershell
# 探针 A：主路径是否累积 checkpoint（缺口 A + C 的返回值印证）
uv run python docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_a_checkpoint_accumulation.py

# 探针 B：revert 的 uuid4 行成为「最新态」的比例，n=60（缺口 B 的定量）
uv run python docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_b_revert_uuid_race.py

# 探针 C：LangGraph 自身的 id 生成器 + 三方 saver 的"最新"表达式 + uuid7 对照（定修法形状）
uv run python docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_c_id_and_latest_semantics.py

# 探针 D：存量 uuid4 回退行是否永久遮蔽后续 uuid6 写入（B2，带双自检）
uv run python docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_d_existing_uuid4_rows_poison.py

# 排除产品代码改动污染
git diff --stat -- applications packages
```

**③ 读数 + 分母**（本目录内文件本体，2026-10-29 复跑；随机 id 部分逐次不同，结构性读数稳定）：

*探针 A* — 主路径每线程 1 条 checkpoint，**id 不变**：

```
第 1 轮后 alist = [('1f1d35ea-d04d-64cc-bffe-0af5500b5ee4', 2)]
第 2 轮后 alist = [('1f1d35ea-d04d-64cc-bffe-0af5500b5ee4', 4)]   ← 同 id，messages 累积到 4
checkpoint 条数 1 轮=1 → 2 轮=1 ；id 是否相同 = True
可回退点 = 1 个，且它是「当前最新态」⇒ 回退目标只能是它自己
```

同探针第 3 节顺带印证缺口 C：revert 后确实多出一行（`1 → 2`），但
`revert success=True … new_cp='1f1d35ea-d04d-…'` —— 返回值是**目标 id**，新行 id 不对外。
第 4 节是对照组：写入时换新 id ⇒ 条数变 2。**所以"不累积"的成因是 append_thread 复用原 id，不是 aput 语义**。

缺口 C 还比"返回值不对"更深一层（源码读出，逐处行号）：`/history` 只读**最新一条** checkpoint
（`applications/agent_server/memory/recall_exact.py:70-75` 走 `aget_tuple` 无 id 分支），而
`HistoryItem.id` 是**消息 id**（同文件 `:45` `getattr(msg, "id", None)`）不是 checkpoint id。全仓 grep
`alist(` 只有本批探针与 `packages/agent-core/tests/test_mongo_checkpointer_async.py:116` 命中 ⇒
**没有任何产品代码路径在列举线程的历史 checkpoint**。即：即使修好 A，客户端仍无处可取 id。

*探针 B* — n=60，全部只调产品函数（`append_thread` / `RevertHandler.revert`）：

```
样本 n=60
revert 返回 success=True 的条数 = 60
其中「新行成为最新态」= 52/60 = 86.7%
★ 静默失效（success=True 但读侧没换）= 8 条 = 13.3%
目标 checkpoint 的 uuid version 集合 = {6}（时序）
revert 新行 uuid version 集合 = {4}（随机）
样例：0: 1f1d vs 1dd8 → False ／ 4: 1f1d vs 1145 → False ／ 6: 1f1d vs e751 → True
```

**口径**：分母 = 60 个独立 thread × 各 1 次 revert；判据"成为最新"= `aget_tuple` 无 id 分支读回的 id == 新行 id。
**理论值核对**：目标 id 前缀恒为 `1f1d`，随机 uuid4 的前两字节 `< 0x1f1d` 即落败，
P = 0x1f1d / 0xffff = **12.15%**；实测 13.3% 与之同量级 ⇒ 读数不是偶发噪声，是**该公式的抽样**。

**同日复跑记录（14:24，四支探针从入库路径原样重跑，rc 全 0）**：

```
探针 B 第二轮：n=60 → success=True 60/60，新行成为最新 = 55/60 = 91.7%，静默失效 = 5 条 = 8.3%
两轮合并：13/120 = 10.8%（二项 95% 区间约 [5.9%, 16.6%]，覆盖理论值 12.15%）
探针 A / C / D 结构性读数逐条一致（A 每线程恒 1 条且 id 不变；C uuid6 连调 1000 次严格递增；
D 3/3 轮“行已落地但读侧不认”，对照组无遮蔽）
ruff check 本目录 rc=0（probe_d 初版落了 I001 + F541，本轮 --fix 后复绿）
```

⇒ **B1 的比例是随机抽样，不是常量**：引用它必须带 n 与区间口径，不得把“13.3%”当契约数字。
缺口成立与比例大小无关——**任何非零落败率都足够否决 uuid4**（B2 的永久遮蔽更是不依赖抽样概率）。

*探针 C* — 修法的形状由这五条锁死：

```
LangGraph base 模块 L19：from langgraph.checkpoint.base.id import uuid6
  empty_checkpoint：id=str(uuid6(clock_seq=-2))    create_checkpoint：id=id or str(uuid6(clock_seq=step))
  连调 uuid6() N=1000（不带 clock_seq）：严格递增 = True；去重后个数 = 1000 / 1000
候选 id vs 产品主路径写出的 id（1f1d35f4-66f8-68b1-… v6）：
  uuid4（现写法） 9f84571d-… ⇒ > 产品 id = True   ← 但这次赢，探针 B 两轮实测 8.3%–13.3% 输
  uuid6（推荐）  1f1d35f4-66fa-… ⇒ > 产品 id = True
  uuid7（直觉）  01a18646-… ⇒ > 产品 id = False  ← 永远输
InMemorySaver.get_tuple：checkpoint_id = max(checkpoints.keys())
AsyncPostgresSaver：WHERE thread_id = %s AND checkpoint_ns = %s ORDER BY checkpoint_id DESC LIMIT 1
                    列定义 checkpoint_id TEXT
MongoCheckpointer（本仓自研）：.sort("checkpoint_id", -1)
checkpoint_cleaner.py（本仓）注释自陈：「checkpoint_id 为 uuid.hex，字典序即写入序，sort(-1) 取最新」
```

⇒ ① 正确 id 族是 **langgraph 自己的 uuid6**（`langgraph.checkpoint.base.id.uuid6`，实测连调 1000 次
严格递增且无重复 ⇒ 推荐修法的排序前提成立，不再只是两次的抽样）；② "换 uuid7 就可排序"的直觉
**被实测否证**（v7 的 `01a1…` 字典序**恒小于** v6 的 `1f1d…` ⇒ 换 v7 会**永远落败**）；
③ InMemory / PG / Mongo 三处读侧表达式**同构**，都是字典序取最大 ⇒ 一处修好才算全修。

*探针 D* — 缺口 B 的重方向（B2，每步双自检通过）：

```
产品路径造出的「已回退」线程：
  目标(v6)        = 1f1d3600-23fb-6330-bffe-556db1dd5d47
  revert 新行(v4) = 3d6a6ecc-9294-4067-a36f-8bdf0f74880f  ⇒ 读侧最新 = 该行（遮蔽目标）
此后按「每轮写新 uuid6」连写 3 轮（模拟修好 A 之后的形态）：
  写 1f1d3600-23fd-6cc3-… ⇒ 行已落地 = True；读侧最新 = 3d6a6ecc-… ⇒ 新行成为最新 = False
  写 1f1d3600-2400-67d7-… ⇒ 行已落地 = True；读侧最新 = 3d6a6ecc-… ⇒ 新行成为最新 = False
  写 1f1d3600-2401-6d6f-… ⇒ 行已落地 = True；读侧最新 = 3d6a6ecc-… ⇒ 新行成为最新 = False
该线程 alist 共 5 行，字典序首位 = 3d6a6ecc-… ⇒ uuid4 回退行永久遮蔽后续 v6 写入 = True
对照组（回退行也用 uuid6）：回退行成为最新 = True；之后写新行仍胜出 = True ⇒ 同族无遮蔽
```

**口径**：分母 = 1 个线程×后续 3 轮写入；"行已落地"= 按该 id 精确 `aget_tuple` 读回且 messages 末条
内容 == 本轮 marker（正控，专防"原地覆写冒充新行"）。对照组同姿势跑⇒ 差异只来自 id 族。

**④ 未跑与待环境**：
- PG / Mongo 态**未实跑**（本机无库）；上表那两行是 langgraph `1.2.16` 源码读出，属**待环境**。
- `checkpoint_cleaner.py` 删错方向为同式推论，**未实跑**（该服务需 federation 环境）。
- 真实部署态（`DATABASE_URL` 有值 ⇒ `get_checkpointer` 返回 `AsyncPostgresSaver`）下的探针 B 复跑：未做。
- 缺口 A 的**产品侧处置**（是否让主路径累积 checkpoint、retention 怎么定）属 **D2**，需人批，本文件不代答。

**⑤ 所需依赖**：
`uv sync --all-packages` 的默认 dev 环境即可，**不需要** `DATABASE_URL` / LLM 密钥 / 任何外部服务
（探针只在 `InMemorySaver` 上跑产品代码）。版本绑定：langgraph `1.2.16`、uuid-utils `0.17.0`、CPython `3.12.13`。
探针 C 的 uuid7 对照依赖 `uuid_utils`（langgraph 的传递依赖，本机可用）——**方案不新增该依赖**，它只用于证伪。

---

## 2. 在册测试为什么没拦住（断言面窄于契约）

`packages/agent-runtime/tests/test_revert.py` 有 `test_revert_creates_new_checkpoint_id`，但它：
1. 播种 id 用字面量 `"cp1"`（**非 UUID**）⇒ 永远走不到"字典序排序"这个真实关系上；
2. 断言只有"目标行仍为 cp1（未被覆写）"，**从不断言新行成为读侧最新态**。

⇒ 契约要求的是"回退后读侧看到回退结果"，测试断言的是"写入产生了一个不同的 id"。**断言面窄于契约**，
13.3% 的静默失效因此长期不可见。这不是测试写错，是它没被测到那一层。

---

## 3. 本轮取证自己踩的坑（作废记录，免得后来者复用错探针）

第一版的手写 `aput` 探针把 `new_versions` 传成了**全量 `channel_versions`**，
覆盖了 InMemorySaver 的共享 blob，读出"旧 id 带 4 条消息"的怪象。
该读数**作废**（未入库），原因写在探针 B 的 docstring 里。

同族第二次（探针 D 第一版，**已当场发现并当场修**）：重写时漏了 `ck["id"] = ck_id` 这一行，
所谓"写新行"其实是**原地覆写最新行**，于是"新行没胜出"与"内容读回来了"两件事同时成立——
矛盾。暴露它的读数很刺眼：对照组的"回退行 id"与"目标 id"**一字不差**。第二版把自检拆成两条
并升为 `assert`：① 按新 id 精确读回内容（正控：证明行真的落下去了）② 写入 id 与读侧最新 id
分开报（不拿"最新"当"我写的那行"）。

纪律：**要测产品行为就只调产品函数**；手写 saver 调用等于在测自己对内部实现的理解，
而理解正是可疑项。如果非写不可（产码还不存在），就必须带**正控**：
光验"读回的内容对"不够，它对自己覆写自己的错写法也会报绿。

---

## 4. 本批工件清单

| 路径 | 性质 |
|---|---|
| `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_a_checkpoint_accumulation.py` | 可复跑探针 |
| `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_b_revert_uuid_race.py` | 可复跑探针（定量） |
| `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_c_id_and_latest_semantics.py` | 可复跑探针（形状/源码证据） |
| `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_d_existing_uuid4_rows_poison.py` | 可复跑探针（B2 遮蔽效应，含双自检） |
| `docs/operations/evidence/2026-10-29-revert-checkpoint-probe/readings.md` | 本文件 |
| `docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md` | 方案（读本文取证据，不重复读数） |

`uv run --with ruff ruff check docs/operations/evidence/2026-10-29-revert-checkpoint-probe` ⇒ **All checks passed!**（rc=0，本批结束实取）。

---

## 5. 收尾门禁复跑（同日第二轮，读数绑 rev `896f966e`，分支 `feat/nl2sql-ttl-and-006-slim`）

| 动作 | 命令（本机逐字可复跑） | 读数 | 它证明什么 / 不证明什么 |
|---|---|---|---|
| 探针可复现 | 逐支 `uv run python docs/operations/evidence/2026-10-29-revert-checkpoint-probe/probe_[abcd]*.py` | 四支 rc=0；A/C/D 结构性读数逐条与首轮一致，**B 第二轮 n=60 得 5/60 = 8.3%**（首轮 8/60 = 13.3%，合并 13/120 = 10.8%，二项 95% 区间覆盖理论值 12.15%）| 证明缺口可复现。**不证明比例是个定值** ⇒ 三处文档已把单点改区间口径 |
| 文档四类断言 | `uv run python .tmp-scratch/selfcheck_docs2.py`（不入库）| 八份件**硬断言失败 = 0**，rc=0 | 证明本批路径/行号/小节锚/条目锚自洽。**不代替 CI**：它是本机会话内脚本，换人不可复取（登记在此是为了可被反驳，不是为了算门禁）。**非空转反证**：收尾时它当场抓到本轮自己新写文本里的一条悬空锚（roadmap 取证件 §4.1 裸写“§11.4”未指文档，已改为“实施件 §11.4”）⇒ 断言在真校东西，不是报“全 0”的摆设 |
| 根三文档未改坏 | `uv run python scripts/check_doc_sync.py` | rc=0（0 警告）| 作用域只有 AGENTS/ARCHITECTURE/README ⇒ **扫不到本批 `docs/` 内部的互相引用**（实施件 §11.4 记的门禁盲区，因此引用边完整性仍只能靠「同批 `git add`」保证）|
| 公开镜像面 | `uv run python scripts/lint_public_mirror.py`（registry 模式）| rc=0（3 文件 30 命中 / 台账 3 项 / 违规 0）| 证明本批新文档未新增内网主机/网段字面量 |
| 零产码改动 | `git diff --stat -- applications packages` | **输出为空** | 本批全部是文档与探针 ⇒ 上一行那条“方案阶段不动产品代码”的约束可核对 |
| 在册测试无退化 | `uv run pytest applications/agent_server/tests/{test_console_router,test_history_real_checkpointer}.py -q`（33 passed）· `packages/agent-runtime/tests/test_revert.py`（11）· `packages/agent-core/tests/test_checkpointer.py`（6）· `tests/memory/test_thread_persist.py`（10）| **合计 60 passed / 0 failed**（分四次跑，避开 conftest 重名）| 证明探针结论所在的那四条链的用例仍绿。**不等于全量门禁**：未跑 `make test`（10 session）⇒ 提交前需按验证策略对齐 CI |

> **入库注记（2026-10-30，只记不改上表正文）**
> - 本件随批次 B2 提交（`git commit db4fea6c`，用户显式批示、逐路径 `git add`、**未 push**）⇒ 下面「诚实边界」里的**未提交**一条已被取代。
> - 同表「公开镜像面」那行是**台账收紧前**的真实读数：批次 B3 把 `_REGISTRY` 从 3 项收到 1 项（`docs/operations/env-126-inventory.md` 与 `deploy/k8s/15-valkey.yaml` 就地脱敏后不再需要登记），换 rev 后该命令的预期读数为 `1 文件 / 命中若干 / 台账 1 项 / 违规 0`（ADR-0013 余下那一处是 PII 正则的**合成示例值**，见该文文首脱敏口径注记）。
> - ⚠ **反向提醒**：在 B3 落地之前的任意时刻复跑该行命令，会读到 **rc=1 / 违规 2**（两条 P-4「携带内网标识但未登记」）。那是「磁盘上的新台账 + HEAD 上的旧真值」混合态的形状C 机制性红，**既不说明上表那行读错，也不是新缺口**；台账收缩与被遮内容必须同批提交，否则两向都红。

诚实边界（本批未做项）：**未提交**（用户规则：提交需显式批示、逐路径 `git add`）；未跑全量 `make test`；未做 E2/现网取证（本批不改运行链路）。
