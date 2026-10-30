# 全量 session 清扫读数：十 session 逐个 rc=0 + 两处口径落差（2026-10-30）

**定位：** 证据记录（不是方案）。格式遵循 `docs/operations/evidence-format.md` §1 五字段 + §3 强度分档。
**对象：** 把 `make test` 的 10 个 pytest session 在**当前 tip** 逐个实跑到 rc 级读数，并顺带核掉
`unconfirmed-items.md` 里"合并根会话未取"（P2）与"skip 归属未复算"两项。
**读数绑定 rev：** `27fb1e41`（分支 `feat/nl2sql-ttl-and-006-slim`），**工作区在跑前已 clean**（`git status --porcelain -uall` 空）
⇒ 下表读数就是 rev 本身那棵树，不是 `HEAD + 未提交` 混合态（这与形状 C 那份取证件的口径不同，别混引）。
**关联：** `Makefile` 的 `test:` 目标（命令逐条抄自它，未改标）、`docs/operations/testing-playbook.md`（"怎么跑"）、
`docs/operations/unconfirmed-items.md` §2（P2/P3 两行据此更新）。

---

## 1. 十个 session（命令 = Makefile `test:` 原样，rev `27fb1e41`）

| # | 命令 | 读数 | rc |
|---|---|---|---|
| 1 | `uv run pytest -q -m "not requires_pg" -rs` | **1486 passed / 10 skipped / 29 deselected in 1908.73s (0:31:48)** | 0 |
| 2 | `uv run pytest packages/shared-schemas/tests -q` | 28 passed in 0.06s | 0 |
| 3 | `uv run pytest packages/agent-runtime/tests -q` | 827 passed / 2 skipped in 9.53s | 0 |
| 4 | `uv run pytest applications/agent_server/tests -q` | 145 passed in 24.80s | 0 |
| 5 | `uv run pytest applications/agent_federation/tests -q` | 192 passed / 1 skipped in 10.42s | 0 |
| 6 | `uv run pytest applications/kefu-service/tests -q` | 49 passed in 16.31s | 0 |
| 7 | `uv run pytest applications/exhibition-agent/tests -q` | 381 passed / 11 warnings in 63.56s | 0 |
| 8 | `uv run pytest applications/knowledge-service/tests -q` | 416 passed / 7 skipped in 8.30s | 0 |
| 9 | `uv run pytest applications/nl2sql-service/tests -q` | 235 passed / 8 skipped in 4.05s | 0 |
| 10 | `uv run --extra otel pytest tests/observability -q` | 18 passed in 14.43s | 0 |

合计 **3777 passed / 28 skipped / 29 deselected**，10 个 session 全 rc=0。计数口径：passed 取 1–10 行汇总表末项相加（3777），
不是任何一次的 `--collect-only`；skip 相加 = 28（deselected 另计，不并进 skip，否则 §2 那个对账会差 1）。

同批另取（都在 `make ci` 链上，逐项当场实取）：`uv run python eval/run_eval.py` → 「启发式路由准确率: 15/15 = 100.00%」rc=**0**；
`uv lock --check` → `Resolved 285 packages in 7ms` rc=**0**；
`lint_public_mirror.py --selftest` / `check_doc_sync.py` / `ruff check .` / `lint_architecture.py` /
`lint_migration_refs.py` / `lint_graph_state_boundary.py` 六件 **全部 rc=0**（后者两件本轮首次实取）。

⇒ **完成强度 = 第二档「标准环境已验证」**（evidence-format §3）：十 session 全绿这一条在本机成立，
但它**不等于** `make ci` 原样通过（本机无 make，P4 仍开放），也不覆盖 requires_pg 那 29 项（被 deselect，不是通过）。

## 2. 口径落差一：`pytest -q` 与 Makefile 的 `-q -m "not requires_pg"` 不是同一个数

本轮之前我在册引用的是 `1487 passed / 38 skipped in 170.64s`（rev `cfc7bf19`，命令 `uv run pytest -q`，**不带 marker**）。
Makefile 的门禁命令带 `-m "not requires_pg"`，本轮实测为 `1486 passed / 10 skipped / 29 deselected`。两数不像同一套件，先做算术对账：

- 不带 marker：1487 + 38 = **1525**
- 带 marker：1486 + 10 + 29 = **1525** ⇒ 收集总数一致，**差在分类不在套件**。
- **下面的分解不是实量，是上面两组实测数逼出来的算术结果**（前提：“marker 只能把用例从集合里拿走，不能把 pass 变成 skip”）。
  设 x = 在无 marker 时“通过”但带 `requires_pg` 的用例数，y = 同样带标记但当时已 skip 的数：
  x + y = 29（deselected 数），且 1487 − x = 1486、38 − y = 10 ⇒ **x = 1 / y = 28**。
  也就是说：有**一个带 `requires_pg` 标记的用例在无 PG 时是“通过”而不是“跳过”**——这个结论只能从计数推出来，本轮没直接抓到它。

⇒ 判定：我此前引用的 1487/38 形状本身没错，但**它不是 CI 命令的形状**；对外说"对齐 `make test`"必须用 1486/10/29。
未闭合的两半：① 上面那个推论的前提“两次收集的是同一套件”本身未校——两数取自**不同 rev**（`cfc7bf19` vs `27fb1e41`，
中间 5 个提交只动过 4 个文件，其中唯一的脚本件 `scripts/lint_public_mirror.py` 是纯注释变更），应用 `--collect-only -q` 计数对比才能坐实；② 那 1 个“标了 requires_pg 却无需 PG 就通过”的用例
是谁、是标记错还是断言空转，**本轮未查**（`-m "requires_pg"` 单跑会让它们去连库，与 §4 的挂起形状撞车，我没在同一轮里混做）。

## 3. skip 归属：10 项逐条（`-rs` 实取，不是文档转述）

| 位置 | 守卫理由（原文） | 判定 |
|---|---|---|
| `tests/governance/test_corpus_tenant_isolation.py:186` | `agent_server/sql 已退役（ADR-0011 §7）；等价判据在 nl2sql 侧` | 设计意图（退役件），非失败 |
| `tests/nl2sql_service/test_settings_precedence.py:62` | `根 .env 未提供 EMBEDDING_MODEL` | 缺配置守卫 |
| `packages/agent-core/tests/test_guardrails_fs.py:116/168/287` | `Windows 建符号链接需特权/开发者模式`（3 项） | 平台守卫 |
| `packages/agent-core/tests/test_guardrails_fs.py:337` | `反斜杠二次解释只在 POSIX 宿主上有意义` | 平台守卫 |
| `packages/agent-core/tests/test_guardrails_fs.py:356` | `本用例断言 POSIX 宿主特有的入参语义` | 平台守卫 |
| `packages/agent-core/tests/test_tracing_degradation.py:77/90/109` | `已装真 SDK：…由 tests/observability 覆盖`（3 项） | 与 §1 第 10 行互斥分流：真 SDK 在场时降级前提不成立 ⇒ 由 otel session 承接，本轮该 session 18 passed |

⇒ **判定：10 项全是"缺环境/前提不成立"的自动跳过，无一项是掩盖失败**（AGENTS.md《conftest 守卫识别》口径）。
这条现在可核对：`-rs` 的 short test summary 原样落 `.tmp-scratch/c-mask/sessions-2026-10-30-fg.log`（本机，不入库）。
其余四个 session 的 skip 数（agent-runtime 2 / federation 1 / KS 7 / nl2sql 8）**本轮只取了总数未逐条列**——
不得由 §3 这 10 项外推成"全部 skip 都已定性"。

## 4. 调用形状会把墙钟时间抽掉一个量级（本轮现场复现，含对自己假设的证伪）

同一条 `uv run pytest -q -m "not requires_pg"`、同一 rev `27fb1e41`、同一组计数（1486/10/29），**两次墙钟差 12 倍**：

| 起法 | 额外旗标 | 读数 |
|---|---|---|
| `powershell -NoProfile -File run_sessions.ps1` | `-rs` | **1908.73s**（rc=0，跑完了） |
| 直接在工具 shell 里跑 | `--durations=15` | **154.91s**（rc=0） |

本轮还出现过第三种形状——同一个 `-File` 包装器下，根 session 与 agent-runtime session **直接冻住**：
CPU 停在 48s / 5.7s 不再增长（每 20–25s 采样一次 Δ=0.0s），且 **TCP 连接 0 条、无子进程、共 3 线程**
⇒ 它在等东西，不在算东西。同一条 agent-runtime 命令改直接起法：**827 passed / 9.53s**。

按实例对齐后得到的归因（n=4 vs n=3，样本小，不是定理）：

| 起法 | 实例 | 结果 |
|---|---|---|
| `-File` 包装器 | 根 session（后台） | 冻死，612s 时砍掉 |
| `-File` 包装器 | agent-runtime（后台） | 冻死，砍掉 |
| `-File` 包装器 | shared-schemas（后台，28 项） | **正常** 0.06s |
| `-File` 包装器 | 根 session（前台转后台） | **慢 12 倍**但跑完 |
| 直接起 | agent-runtime / governance / 根 session | 全部正常 |

⇒ **判定：退化只出现在包装器起的实例上**，且唯一不受影响的包装器实例是输出量最小的那个（28 项只打 1 行）
⇒ 形状上像“输出/控制台背压”而不是“套件真慢”。**具体机制本轮未归因**：
我先下的“后台起必冻”这个结论被后面的读数推翻了——直起 + 后台转发的根 session 是 154.91s 正常跑完的，
所以变量不是“前/后台”，是“有没有经过这层包装器”。

**可执行约束（建议归 `testing-playbook.md`，本轮没动手改它）**：长跑 session 一律直接起命令，别过 `-File` 包装器；
**墙钟耗时不得跨调用形状比较**（否则拿两种环境比），跨形状时只能引用 rc 与计数。

**它直接推掉台账 P3**：`unconfirmed-items.md` P3 记的是“`tests/governance` 整目录超 9 分钟未完，原因未查明”。
本轮实测：`uv run pytest tests/governance -q` = **464 passed / 1 skipped in 102.58s**（与今早同目录的 102.86s 同值）。
⇒ “超 9 分钟”不是 governance 的固有成本，也不是机器变慢；与 §4 的包装器退化同族。P3 已据此改状态。

## 5. 慢点读数（`--durations=15`，rev `27fb1e41`，该次总墙钟 154.91s）

Top-15 合计 **113.17s**（逐项相加，不是仪表给的聚合值），剩下 1481 项共约 41.7s ⇒ 套件本身不慢。

| 耗时 | 用例 | 定性（本轮读码得到，不是猜） |
|---|---|---|
| **31.69s** | `packages/agent-core/tests/test_checkpointer.py::test_get_checkpointer_uses_mongo_when_configured` | 占根 session 总墙钟的 **20.5%**（31.69/154.91）。本机无 mongo ⇒ 走降级分支。用例先调 `get_checkpointer()`（L43），再调探测函数 `_mongo_reachable(url, timeout_ms=1500)`（L44）——后者自带 1.5s 上限，**不是它慢**；慢在工厂那条链：`agent_core/memory/__init__.py:94-108` 读 `MONGO_URL` → `mongo_checkpointer.py:95` 是裸 `MongoClient(mongo_url)`（无任何超时参数），L100 的 `create_index` 是首个 I/O ⇒ 降级前要先等完驱动默认的 server selection 周期。用例本身行为正确（两支断言），代价是“无 mongo 时也要付 30s”<br>⚠ **本行初稿写的是 `agent_core/memory/mongo.py:40`，那是错的**：那个类是会话历史（`MongoMemory`），本用例经 `get_checkpointer()` 走的是 `mongo_checkpointer.py`。两处都裸，但不是同一条路径 —— 我先把结论挂到了兄弟件上，靠 §5.1 逐层读码才分开。 |
| 14.69s | `tests/api/test_api_smoke.py::test_query_sse_direct_route` | 未查（本轮只定位到“不是它造成 §4 的 12 倍差”，因为两次都有它） |
| 9.52s | `tests/governance/test_path_io_governance.py::test_p7_current_tree_has_zero_violations` | 不变量 lint 全仓扫描类（同族还有 5.86/5.64/5.34/5.24/5.23/5.12/5.00/4.81/4.78/4.66s 那几条）⇒ 门禁类用例是 Top-15 里占 11 席的主体，这不是问题而是代价 |
| 2.80 / 2.79s | `test_graph_state_boundary_gate.py` 两条 | 同上族 |

⇒ 判定：套件不慢；固定开销在两类东西上——**没带超时的 mongo 客户端**（30s，见 §5.1）与**一批全仓扫描的架构门禁用例**。
前者是韧性/超时策略问题（横切关注点，按 AGENTS.md 不能就地各修一处，已转台账 D27）；后者是门禁本来该有的代价。

### 5.1 把“默认 30s”从引用文档改成实量（同日下午补取，本机无 mongo）

上一版我在 §5 里写的是“pymongo 官方默认 30000ms，该默认值本轮未实测”——那是**拿文档当读数**。本轮用最小探针直接量：
`uv run python .tmp-scratch/c-mask/probe_mongo_timeout.py`（脚本在 gitignored 区，不入库 ⇒ 下面的数字需在自有环境复跑才算可核对）。

| 探量 | 读数 | 判据意义 |
|---|---|---|
| A `MongoClient(url)` + `create_index`（生产路径形状） | **30.44s** → `ServerSelectionTimeoutError`（`WinError 10061` 目标计算机积极拒绝） | 默认 server selection 超时 = 30s 这一条**现在是实量**，不是文档转述 |
| B 同 URL + `serverSelectionTimeoutMS=1500` | **1.52s** → 同类异常 | 旋钮有效：一行参数就能把 30s 压到 1.5s（⇒ 修法是小的，争议在“该不该由共享包定这个值”） |
| C `MongoClient(url)` + `admin.ping`（换首个 I/O） | **30.45s** → 同类异常 | 成本**不在 `create_index` 本身**，在 server selection：换任何首个操作都是这个数 |
| D `MongoClient(url)` 仅构造不触 I/O | **0.00s** → `no-raise` | 构造是惰性的 ⇒ 计时起点在首个操作，不是在建客户端 |

算术自洽：A 30.44s + B 1.52s = **31.96s**，与 §5 的 31.69s 同量（差 0.27s，探针与用例的 URL/集合名不同，不强行对齐）
⇒ 31.69s 可分解为“生产路径 30s + 探测 1.5s”，不存在第三块未知的慢。

⇒ 判定：**两处**生产 `MongoClient` 均无超时参数（`mongo_checkpointer.py:95` 检查点、`mongo.py:40` 会话历史），
全仓 `git grep -n -I "MongoClient(" HEAD -- packages applications` = **3 处命中**（2 裸 + 1 个测试侧带 1500ms）。
两处同形 ⇒ 正是“不能就地各修一处”的那个理由，已登 D27。

一条**排除掉的解**（读码得到，不是猜）：`agent_core/resilience.py:200` 已有 `timeout(seconds)` 装饰器，但它是线程池
包装且 `ex.shutdown(wait=False)`（L222）——**不取消底层调用**；再叠上 D 探量“构造 0.00s”（构造惰性），
装饰构造无效、装饰首个操作只是把等待方换成 `TimeoutError` 而驱动仍在跑 ⇒ 本例的真旋钮只在驱动参数。

⚠ **仪器自纠（差点写进去一条假“没有”）**：取上面那句之前我先跑 `git grep -n -I -E "timeout|backoff|retry" HEAD -- .../resilience.py`，
它夹在一串语句里（后面那个 `Select-String` 因路径不存在报错），**屏幕上没回显任何命中行** ⇒ 我按“零命中”理解，
差点在 D27 里写成“`resilience` 里出现超时原语”当**将来时**的复审条件。单独复跑同一条命令（逐字一致）：rc=**0**、**40 行命中**，
`timeout`/`retry`/`retry_async`/`CircuitBreaker` 都在。⇒ 又是一次“**空显示被当成空结果**”（与 §4 那个被 `Select-Object` 咽掉的 traceback 同族）；
差别只在于这次我在下结论前回头复跑了，而写进文档的是复跑后的值。教训：**取阴性要单独跑、并看 rc**，不拿混在一串里的输出当零。

## 6. 本轮未跑 / 不得读成已验

- `make ci` / `make test` 的**原名命令**（本机无 make，P4 仍开放）——本轮是逐条等价命令，不是同一个可执行体。
- 29 项 `requires_pg` 被 deselect ⇒ **真库用例本轮零覆盖**（不是“通过”，是未跑）。
- 其余四 session 的 28 项 skip 未逐条定性（§3）；§2 那个 x=1 推论未直接抓到实体。
- 变异杀死率（`make mutation-cache`）、黄金集以外的 E2/E3、红队、canary：本轮未碰。
- 126/241 现网侧：本轮未碰（零产品代码变更 ⇒ 不改变现网态，也不拿它当本轮读数的一部分）。
- §4 的机制归因：未归因。要定它需要拿包装器与非包装器各跑一次同旗标（本轮 `-rs` 与 `--durations=15` 旗标不同，
  严格说 §4 那张表里两行不同旗标，只能支撑“差 12 倍”这个事实，不能支撑“旗标无关”这个推论）。
