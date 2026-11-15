# 可选外部依赖的探活超时收敛（D27 = b）：mongo 客户端小工厂 + 门禁 P15

**版本：** V1
**状态：** **已拍板方向（D27 = b），待施工**——本文只做定夺与排期，未改一行产品代码。**2026-10-30 答复批随动**：本文原有的两个待答已由用户答完（默认值 `2000` **已确认**；排期 = **前端之后**）⇒ 文中已无欠答项，但 **S1 仍未获开工授权**，一行代码未动。
**依据：** 全部坐标于 rev `9e9ce198` 本轮重取；代价读数引 `docs/operations/evidence/2026-10-30-full-session-sweep/readings.md` §5 / §5.1（rev `27fb1e41`，换 rev 须复跑）。
**坐标免检入口（2026-10-30 补）**：判「要不要重取」不能用「非 `docs/` 文件清单」那种口径——它会把与本方案无关的 `scripts/evidence/*.py`（账面随动脚本）也算成警报；必须按**被引路径** scoped 现取：`git diff --name-only 9e9ce198..HEAD -- packages/ scripts/lint_architecture.py tests/governance/ applications/ ARCHITECTURE.md CHANGELOG.md` ⇒ 当前输出 **0 行**。另实读复核三处关键坐标：`packages/agent-core/agent_core/memory/mongo.py:40` 与 `mongo_checkpointer.py:95` 两处裸 `MongoClient(mongo_url)` 仍在、`packages/agent-core/tests/test_checkpointer.py:62` 的 `_mongo_reachable` 副本仍在。**清单非空 ⇒ 重跑取证件，不得引用本行。**
**回写：** 落地后必须回来把本行改为「已落地(<commit>)」，并同步台账 D27 状态行与 §5 那张计数表。
**判据对象：** `docs/operations/unconfirmed-items.md` §3 **D27**（用户 2026-10-30 选 b）。

---

## 0. 结论先行（做什么 / 不做什么）

1. **单一实现**：新增 `packages/agent-core/agent_core/memory/mongo_client.py`，导出四个名字——
   `DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 2000`、`new_mongo_client(mongo_url, **overrides)`、
   `server_selection_timeout_ms()`、`is_reachable(mongo_url, timeout_ms=None)`。
2. **全局装配**：两处生产裸构造（`memory/mongo_checkpointer.py:95`、`memory/mongo.py:40`）改为调 `new_mongo_client`；
   测试侧那份带超时的探测实现（`packages/agent-core/tests/test_checkpointer.py:62-74 _mongo_reachable`）**删除本地副本**，改调 `is_reachable`。
3. **强制门禁**：lint 新增 **P15**（三条判据，见 §4），配 `tests/governance/test_mongo_probe_governance.py`。
4. **新 env**：`MONGO_SERVER_SELECTION_TIMEOUT_MS`，默认 `2000`（毫秒）。非法值 ⇒ **警告 + 回退**（内核家法），不新造异常类型。逃生阀 = 显式设 `30000` 回到驱动默认。
5. **本批不做**（逐项理由见 §9）：`create_index` 不动、`socketTimeoutMS` / `connectTimeoutMS` 不动、`/health` 降级可见性另登一条、
   KS 的 MinIO/Milvus 同族形状不动（**本轮未测其代价**）、`MONGO_*` 全族裸读不收敛（宽口径需另拍板）。

⇒ 交付后「无 mongo 环境」的等待从 **30s 级**变成 **2s 级**，且第三处裸构造会被 CI 拦住，而不是靠评审记得。

---

## 1. 问题陈述（每条都带本轮实测坐标）

| # | 事实 | 坐标 / 命令 |
|---|---|---|
| F1 | 全仓 `.py` 里 `MongoClient(` **3 处**：生产 **2 处裸**（无任何超时参数）+ 测试 1 处带 `serverSelectionTimeoutMS=timeout_ms` | `git grep -n "MongoClient(" -- "*.py"` → `memory/mongo.py:40`、`memory/mongo_checkpointer.py:95`、`packages/agent-core/tests/test_checkpointer.py:69` |
| F2 | 两处生产形状相同：`MongoClient(url)` → 取 collection → **首个 I/O 是 `create_index`** | `mongo.py:40-44`（索引 `session_id`+`ts`）、`mongo_checkpointer.py:95-104`（四字段 unique 复合索引） |
| F3 | **唯一"探活带超时"的实现长在测试里**，生产在外面 ⇒ AGENTS.md《架构决策原则》判定的反模式（横切关注点每处各自实现，且实现放错了层） | `tests/test_checkpointer.py:62 _mongo_reachable(url="mongodb://localhost:27017", timeout_ms=1500)`，:44 被用例调用 |
| F4 | 降级链本身是对的（**别改它**）：`memory/__init__.py:94` 读 `MONGO_URL` → :101 构造 → :109 `except Exception` → :112 `logger.warning("MongoCheckpointer 初始化失败，降级 InMemorySaver: %s")` → :115-117 返回 `InMemorySaver()`。慢发生在**进 except 之前** | 优先级 `pg_pool → MONGO_URL → InMemorySaver`（:83-117） |
| F5 | 代价已实量（取证 §5.1，rev `27fb1e41`）：裸构造 + `create_index` = **30.44s** 才抛 `ServerSelectionTimeoutError`；换 `admin.ping` = **30.45s**（成本在 server selection，不在 `create_index`）；仅构造 = **0.00s**（构造惰性）；同一 URL 加 `serverSelectionTimeoutMS=1500` = **1.52s** | 探针 `.tmp-scratch/c-mask/probe_mongo_timeout.py`——**本机文件，不入库** ⇒ 换机器须照本行写的四个形状自建，读数只在同形状下可比 |
| F6 | 门禁墙钟：根 session 最慢用例 `test_get_checkpointer_uses_mongo_when_configured`（`tests/test_checkpointer.py:23`）= **31.69s**，占该 session 总墙钟 154.91s 的 **20.5%**（分解：生产路径 30s + 探测 1.5s，与 F5 的 30.44+1.52=31.96 同量） | 取证 §5 / §5.1；根 session = `Makefile:56 uv run pytest -q -m "not requires_pg"`（其口径含 `agent-core/tests/`，见 `Makefile:37-38` 注） |
| F7 | 请求路径同样吃这笔钱：`MONGO_URL` 配错或 mongo 宕时，`get_checkpointer()` 要阻塞 **30s** 才降级 ⇒ 冷启动/首请求白等 | F4 的 :101 → F2 的首个 I/O |
| F8 | 下游不止一家：knowledge-service 经兼容 shim 复用同一个内核类 ⇒ 改 agent-core 顺带修 KS，**不需要单独动 KS** | `applications/knowledge-service/knowledge_service/clients/mongo_history_utils.py:13,25`；KS 侧默认值 `mongodb://localhost:27017` 是**非空**（`knowledge_service/core/config.py:101`）⇒ 无 mongo 时 KS 首次取历史也会付这笔等待（懒加载，`_get_store()` 首调） |
| F9 | 仓内已有**正确形状的样例**（本轮实读，不是模式猜）：客户端构造集中在一处、超时来自 config 单点 | `packages/agent-runtime/agent_runtime/cache/valkey_backend.py:146-153`（`socket_connect_timeout=cfg.connect_timeout_ms/1000`、`socket_timeout=...`、`retry_on_timeout=False`、`health_check_interval=30`）+ `cache/config.py:79-80`（默认 50 / 100ms） |
| F10 | **两条家法在此冲突**：cache 侧对 `value <= 0` **抛 `CacheConfigError`**（docstring 自述理由：启动期必须失败，不许静默换后端）；而 `agent_core/config.py:62-71 env_int` 对非法值是 **logger.warning + 回退默认** | `cache/config.py:29-33` vs `agent_core/config.py:8`「非法值记警告并回退默认」 |
| F11 | 新旋钮的取值**可被瞬时断言，不必等 30 秒**（本轮补的第二台仪器）：`client.options.server_selection_timeout` 传 `serverSelectionTimeoutMS=2000` ⇒ **2.0**；不传 ⇒ **30** | `uv run python -c "from pymongo import MongoClient; print(MongoClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=2000).options.server_selection_timeout, MongoClient('mongodb://127.0.0.1:27017').options.server_selection_timeout)"` → `2.0 30`（构造惰性，无 mongo 也返回） |
| F12 | 降级目前在健康面**不可见**：`/health` 无 mongo/checkpointer 字段 | `applications/agent_server/api/health_router.py:39-75` 逐字段读毕；`git grep -nE "mongo|checkpoint|history_backend|memory_backend" -- packages/shared-schemas/shared_schemas/health.py` = **0 命中** |

---

## 2. 为什么是 b，以及 F10 那个冲突怎么定

**三选一里为什么排除 a / c**（选项原文见台账 D27）：

- **a（两处各加参数 + 从 env 读）**：代价数字一样能降下来，但它把「探活该等多久」这条策略**复制成两份**，
  且默认值要在两处各自决定——历史上同一开关两套默认值正是 P14 ② 立项的原因（`lint_architecture.py:1156-1157` 注）。
  按 AGENTS.md《架构决策原则》，缺「单一实现」与「强制门禁」两层 ⇒ 只是约定，迟早被第三处破窗。
- **c（维持现状）**：降级语义确实对，但 F6/F7 两笔钱都在**真实路径**上（门禁墙钟的单条最大项 + 首请求 30s 阻塞），
  而 c 等于承认「慢是产品行为的一部分」。这不是不可改，是**没人拍板就说它可接受**。
- **b** 的净增成本 = 一个新模块（约 40 行）+ 一条 lint 判据 + 一个治理用例；收益 = 三处收敛成一处 + 未来同类依赖有现成挂载点。

**F10 家法冲突的定夺（本文拍，不留给实现者）**：取 **警告 + 回退**，不抛新异常。判据：

| 维度 | cache（抛） | mongo（回退） |
|---|---|---|
| 依赖性质 | 主链路，选错后端 = 语义分叉 | 可选依赖，失败即降级为 `InMemorySaver`（F4 已是契约） |
| 忽略一次配置的后果 | 悄悄换了一条正确性不同的轨道 | 多等 ≤2s（或早 1s 判不可用），**不是正确性事件** |
| 抛错的连带代价 | 启动期失败，运维看得见 | 会把「可选依赖配错」升级成 checkpointer 路径**硬失败**，与 F4 的降级契约相反 |

⇒ 不新写 ADR：判据可从两处现有 docstring 直接归纳（主链路 fail-fast / 可选面 warn+回退），且可被单测核对；
把它写成 `agent_core/config.py` docstring 的一条约定 + 台账留字即可。**复审触发条件**：出现第三种「可选依赖」也要定默认超时（届时这条约定该升级为 ADR，因为要谈的是家法而不是某个数）。

---

## 3. 设计（单一实现本体）

新文件 `packages/agent-core/agent_core/memory/mongo_client.py`：

```python
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 2000
ENV_SERVER_SELECTION_TIMEOUT_MS = "MONGO_SERVER_SELECTION_TIMEOUT_MS"

def server_selection_timeout_ms() -> int: ...      # env_int 解析 + 值域守卫（见 R2）
def new_mongo_client(mongo_url: str, **overrides): ...   # 唯一 MongoClient 构造位
def is_reachable(mongo_url: str, timeout_ms: int | None = None) -> bool: ...  # 有界 ping
```

| # | 规则 | 为什么 |
|---|---|---|
| R1 | kwargs = `{"serverSelectionTimeoutMS": server_selection_timeout_ms()}`，再 `**overrides` 覆盖（显式调用方优先于 env） | 留一条"这次就是要不同值"的正路，免得后人又去裸构造 |
| R2 | `env_int` 已把非整型处理成警告+回退；本函数再加**值域守卫**：`<= 0` 或 `> 60000` ⇒ `logger.warning` + 回退 `2000` | `0` 在 pymongo 语义是「立即失败」，不是「不超时」；负值/超大值是配置错误，不该被静默采纳 |
| R3 | 逃生阀 = 显式 `30000`（回到驱动默认）。**不提供"无限等待"选项** | 有界等待是这条策略的唯一意义；无界 = 把 F7 的 30s 换成 ∞ |
| R4 | 模块层**不得 import pymongo**（pymongo 在函数体内懒导入）。`agent_core/memory/__init__.py:37` 是无条件模块级导入本包，且 README:18 自述「base 纯 stdlib；mongo 实现 extra `memory-mongo`」 | 否则 `import agent_core.memory` 会在未装 extra 的环境当场炸——现在它能装上是靠两个消费方各自懒导入 |
| R5 | `is_reachable` 用**同一个默认值**（不再另写 1500）并做 `admin.command("ping")`，异常一律返回 `False` | 收掉 F3 的测试侧副本，让"探活该等多久"全仓只剩一个数 |
| R6 | `create_index` 留在两个消费方原地，**不搬进工厂** | 索引是各自的 schema，不是连接策略；搬进去会把影响面从"一行 kwargs"扩成"schema 归属"，且 F5 的 C 探量已证明慢不在它 |
| R7 | 两个消费方**原有的 try/import 块位置不动**（它们还要 `ASCENDING` / `DESCENDING` / `ObjectId`，缺依赖时那句 `请安装 agent-core[memory-mongo]` 的 ImportError 文案也必须不变），只把调用行换成工厂，并把 `MongoClient` 从导入元组里剔掉 | 留着 `MongoClient` 这个名字而不判它 —— P14 ⑥ 的口径就是「只 import 类名不算违规」（`lint_architecture.py:1196-1197`）；但留着它会触发 ruff F401 ⇒ 必须删名字，不能删整个 import 块 |

**默认值取 2000ms 的理由**：F5 证明 1500ms 已能在"完全无 mongo"时判出不可用（那是拒绝连接，不是慢）；
2000ms 给"实例活着但跨 WAN 慢"留余量，同时把 F6/F7 的 30s 压掉一个量级。
⚠ 这条余量**本机无法验证**（本机没有 mongo）——所以 §7 A4 与 §8 第 1 条把它挂到现网取证；
数值本身属 D1（可逆 + 中影响：env 随时可覆盖），S1 提交前需确认 2000 这个数 —— **已确认（2026-10-30 用户答复批）**。
余量那一侧仍本机验不了：判据落在 §8 第 2 条与 S5，现网取到真实 server selection 时延后若 >2s，改的是本文这个数**并重跑 A1–A3**，不是给某一处单独开例外。

---

## 4. 门禁 P15（三条判据 + 归属）

照 P14 的既有形状实现（`scripts/lint_architecture.py:1153-1240` 一族：头注释 + 白名单元组 + `check_*` + 单文件判定抽出以便正反例）。

| 判据 | 内容 | 被检对象 | 白名单 |
|---|---|---|---|
| ① 构造位 | 出现调用形 `MongoClient\s*\(` 即红 | `_iter_scanned_py_files()`（`:325-331`，全仓 `*.py`） | **只允许** `packages/agent-core/agent_core/memory/mongo_client.py` |
| ② 禁裸读 | `os.getenv` / `os.environ.get` 以字面量读 `MONGO_SERVER_SELECTION_TIMEOUT_MS` 即红 | 同上 | **无**（工厂走 `env_int`，本来就不该出现裸读） |
| ③ 存在性 | `mongo_client.py` 内必须出现字面量 `serverSelectionTimeoutMS` ≥ 1 次，缺即红 | 单文件 | 无 |

三条口径说明（都来自本仓既有代价，不是新发明）：

- **① 只认调用形**：docstring 里写 `MongoClient(...)` 会误报——本仓文本判据的既有代价，`lint_architecture.py:1196-1197` 已把它写成注记；本方案件的说明一律写「MongoClient 构造」。
- **③ 才是真正守住旋钮的那条**：① 只保证"构造都在工厂里"，有人把工厂里那行 kwargs 删掉时 ① 不会红。所以必须有 ③，并配 §7 A5 的变异反证。
- **测试面不在 lint 射程**：`_skipped_rel`（`:396-402`）对 `tests/` 与 `/tests/` 一律排除，P 系列同口径 ⇒ F3 那份副本**不是被 lint 逼着删的**，而是被 R5「全仓只剩一个数」这条设计约束删的。这句话必须留在文档里，否则后人会以为 lint 覆盖了测试。
- 失败口径 = fail-closed（读不到文件即报红），与 P14/P12 一致。

**P15 编号已被核过为空位**：本轮 `uv run python scripts/lint_architecture.py` 实打印 18 个标签
（P4-2 / P2 / R19 / P5 / P6 / P7 / P8 / P9 / P10 / P11 / P12 / P13 / P14 + L-1 / L-2 / L-3 / L-4 / L-5），无 P15。

---

## 5. 影响面（逐文件，全部本轮实读坐标）

| 文件 | 现坐标 | 改动 | 风险 / 备注 |
|---|---|---|---|
| `packages/agent-core/agent_core/memory/mongo_client.py` | 新建 | 三个函数 + 两个常量（约 40 行，R1–R6） | 唯一新增实现 |
| `packages/agent-core/agent_core/memory/mongo_checkpointer.py` | :88 导入块、:95 构造 | `MongoClient` 从导入元组移除，改 `from ...memory.mongo_client import new_mongo_client`；:95 改调工厂 | :96-104 与 except 分支不动 |
| `packages/agent-core/agent_core/memory/mongo.py` | :30 导入元组、:40 构造 | 同上（:41-48 不动） | 两处 except 仍兜住工厂抛出的任何驱动侧异常 |
| `packages/agent-core/agent_core/memory/__init__.py` | :5-13 子模块清单、:37 | docstring 加一行 `mongo_client`；不在模块层导出工厂（消费方按需 import，避免 base 面扩号） | :94-117 降级链**一行不改** |
| `packages/agent-core/tests/test_checkpointer.py` | :62-74 `_mongo_reachable`、:44 调用 | 删本地副本，改 `from agent_core.memory.mongo_client import is_reachable` | 行为等价性靠 A1 计时 + 该用例两支断言不变 |
| `packages/agent-core/tests/test_mongo_client_factory.py` | 新建 | A2/A3 的单元断言（`options.server_selection_timeout`，无需真库） | 进根 session（`Makefile:37-38` 口径） |
| `scripts/lint_architecture.py` | 头 docstring :27-28 之后、P14 段之后、`main()` :1408+ | 新增 P15 段（①②③ + `_mongo_probe_py_violation(rel, text)` 抽出）与 `main()` 打印分支 | 打印数 +1 → §5 末计数表 |
| `tests/governance/test_mongo_probe_governance.py` | 新建 | 正/负例 + 现树零违规 + ③ 的存在性用例，模板照 `tests/governance/test_cache_single_track_governance.py:16-24`（`_load_script` + `parametrize`） | `tests/governance/` 现 38 个 `.py`（含 `__init__.py`），一件一文件 |
| `packages/agent-core/README.md` | :18 模块表、:25-41 env 清单（:40 是 `MONGO_URL / MONGO_DB` 行） | 加 `agent_core.memory.mongo_client` 一行 + 加 `MONGO_SERVER_SELECTION_TIMEOUT_MS` 一行 | 表头就写着「新增 env 必须登记」，不登记即违反在册约定 |
| `packages/agent-core/agent_core/config.py` | :13-28 env 表、:8 家法句 | 表里加该 env；把「主链路 fail-fast / 可选面 warn+回退」写成 docstring 一条约定 | 不改 `env_int` 行为 |
| `ARCHITECTURE.md` | §4.1 表（现 **18 行**）+ 计数口径段 :135 | 加 P15 一行；口径段三个数随动（见下表） | 口径段是"对外陈述门禁强度"的唯一权威，不随动它就是说谎 |
| `docs/operations/unconfirmed-items.md` | **C5 :78、D27 :68**（2026-10-30 重取） | C5 计数随动；D27 状态改「已拍板 b，方案件 = 本文件，施工中/已落地」 | 台账是活文档，就地改。**本行坐标曾写 `:76`/`:66`**（rev `9e9ce198` 的快照），而 §3 那段计数订正块自己长了 2 行就把它们推走了 ⇒ 活文档的行号不许照抄，动手前现取：`(Select-String -Path docs/operations/unconfirmed-items.md -Pattern '^\| (C5|D27)').LineNumber` |
| `docs/architecture/agent-harness-capability-map.md` :353、`docs/project-introduction-2026-10-12.md` :16 | 都写了门禁条数 | 随动 | 这两处是**散引**。本轮实查 `tests/` 下 `lint_architecture` 的 12 处引用，全部是「`_load_script` + 单条规则正反例」形状（P7/P8/P12/P14/R19/L-4/身份门 …），**无一处断言门禁总条数** ⇒ 总数错了不会有人报红，只能靠本表逐条改 |

**计数随动的权威口径**（本轮实取，rev `9e9ce198`；落地后一律重跑再写）：

| 口径 | 现值 | 落地后预期 |
|---|---|---|
| `main()` 打印 P/L 编号（不含 R19） | **17**（含 R19 共 18 标签） | 18（含 R19 共 19） |
| §4.1 表 body 行 | **18**（P 13 + L 5） | 19（P 14 + L 5） |
| 实现函数 | **20** = `check_*` 19 + `check()` 1 | 21 = 20 + 1 |

取数命令（逐字可跑；**故意不放进表——表格单元里的 `\|` 转义会让复制出来的正则失效**，本轮实测两条同形命令给出 0 与 18 两个数）：

```powershell
uv run python scripts/lint_architecture.py | Select-String -Pattern "^(P|L-|R19)"   # 现值 18 行输出
(Select-String -Path ARCHITECTURE.md -Pattern '^\| (P|L-|R19)').Count                # 现值 18
(Select-String -Path scripts/lint_architecture.py -Pattern '^def check_').Count      # 现值 19
```

---

## 6. 迁移策略（5 步，每步独立可提交、独立可回滚）

| 步 | 内容 | 提交面 | 回滚方式 | 开工前是否需再拍板 |
|---|---|---|---|---|
| **S1** | 建 `mongo_client.py` + `test_mongo_client_factory.py`（A2/A3）。**不接线**，生产文件一行不动 | 2 文件 | revert 该提交，无消费者受影响 | 默认值 `2000` 已确认（2026-10-30）；**开工授权仍缺**，且用户定排期 = 前端 PR-0 之后 |
| **S2** | 两处生产构造改调工厂 + 删测试侧 `_mongo_reachable` 副本 + 两个 docstring/README 登记 | 6 文件 | revert 即回 30s 行为（F4 降级链未动，故无数据面风险） | 否 |
| **S3** | 加 P15（①②③）+ `test_mongo_probe_governance.py` | 2 文件 | 单独 revert：S2 的收敛仍在，只是失去防回潮 | 否 |
| **S4** | 计数随动（§5 那 4 处 + 台账 D27 状态行 + 本文状态行） | 5 文件 | 文档批，可与 S3 并行准备但**必须晚于 S3**（否则口径段先于规则改，中间态说谎） | 否 |
| **S5** | 现网取证（§8 第 1、2 条） | 只进出证件 | — | 需环境放行 |

⇒ **S3 必须晚于 S2**：P15 ① 在当前树会报 **2 处违规**（F1 那两处），先加 lint 就是让 CI 红着。
这条顺序不是洁癖，是"S2 改完的树才能承接 S3 的现树零违规断言"。

---

## 7. 验收标准（每条 = 命令 → 期望读数 → 判定；缺任一条不得说"已落地"）

| # | 判据 | 命令 | 期望 |
|---|---|---|---|
| A1 | 慢用例降下来了 | `uv run pytest packages/agent-core/tests/test_checkpointer.py -q --durations=5` | 全绿，且最慢用例 **< 6s**（R5 后 = 工厂 2s + 探测 2s 两次有界等待之和，不是单次 2s） |
| A2 | 工厂默认值可断言、不需要真库 | 见 F11 那条 `python -c` 形状，改为对 `new_mongo_client(url).options.server_selection_timeout` 断言 | `== 2.0` |
| A3 | env 生效 + 值域守卫 | `MONGO_SERVER_SELECTION_TIMEOUT_MS` 依次取 `500` / `30000` / `0` / `-1` / `abc` / 空串 | 前两个 ⇒ `options.server_selection_timeout` 分别 `0.5` / `30.0`；后四个 ⇒ 回退 `2.0` **且不抛**，`caplog` 里必须有警告（无日志即判失败——静默回退等于没有守卫） |
| A4 | 有 mongo 时不降级（**本机不可验，标待环境**） | 现网/KS 侧真实 `MONGO_URL` 下跑 `test_get_checkpointer_uses_mongo_when_configured` | 走 `isinstance(cp, MongoCheckpointer)` 分支；同时取一次真实 server selection 时延，判 2000ms 够不够（不够则本文默认值改数并重跑 A1–A3） |
| A5 | P15 非空转（变异表见 §7.1） | `uv run python scripts/lint_architecture.py` + `uv run pytest tests/governance/test_mongo_probe_governance.py -q` | 现树 0 违规、rc=0；四条变异各自报红 |
| A6 | 既有面不回归 | `uv run --with ruff ruff check .`、`uv run python scripts/check_doc_sync.py`、`uv run pytest packages/agent-core/tests -q`、`uv run pytest applications/knowledge-service/tests -q`（F8 下游） | 全 rc=0；KS 侧无需改动即受益，若 KS 有用例断言"无超时"则**必须改产品代码而不是改断言**（AGENTS.md 测试红线） |
| A7 | 墙钟收益要说成"实测"还是"预期" | 根 session：`uv run pytest -q -m "not requires_pg"`（同 rev 单跑一次即 A1 的分母版） | 31.69s → 实测值（**不得引用"预期 ~4s"当读数**）；总墙钟随动只在与**取证 §5** 同形状（直接起命令、不过 `-File` 包装器）时可比 |
| A8 | 登记齐备 | `git grep -l "MONGO_SERVER_SELECTION_TIMEOUT_MS" -- "*.py" packages/agent-core/README.md` | **4 个文件**命中：`mongo_client.py`、`agent_core/config.py`、`scripts/lint_architecture.py`、`packages/agent-core/README.md`（只限 `.py` + README 是为了分母不被本文与台账的 `.md` 命中掺进来） |

### 7.1 新增门禁的非空转反证（`docs/operations/evidence-format.md` §4 要求的形状）

| 变异 | 期望 | 命中判据 |
|---|---|---|
| 在 `agent_server` 某文件加一行 `MongoClient("mongodb://x")` | **红** | ① |
| 在任意非工厂文件加 `os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS")` | **红** | ② |
| 删掉 `mongo_client.py` 里的 `serverSelectionTimeoutMS=` kwarg（回到裸构造语义） | **红** | ③ —— 这张表里唯一"① 不红而 ③ 红"的一行，也是必须有 ③ 的证据 |
| 把工厂里的调用形改成 `MongoClient` 纯文本提及（无左括号） | **不红**（负控：判据只认调用形） | ①③ 均不应击中 |

测这张表的纪律（不是第五行变异）：临时树必须**铺完整基线、只扰动一个对象**——只铺"要测的那两处"会得到"无法解析"而不是我要测的分支，这条坑已记在 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §31 末段。

---

## 8. 本机验不了的事（按证据格式第 3/4 档写，不许在本批说"已验证"）

1. **A4 全部**：本机无 mongo ⇒ 只验"降级正确且快"，验不了"接得上时不降级"。需现网环境（三台可用性见 `docs/operations/env-126-inventory.md` §9）跑一次并取真实 server selection 时延。
2. **默认值 2000ms 的对外承诺**：它把「无 mongo 从慢但能用」改成「2s 判不可用」。真·慢速 mongo（跨 WAN / 副本集 stepdown >2s）会被误判为宕并降级 —— **本轮没有该场景的任何读数**，只有 §8.1 的缓解路径。
3. **`make ci` / `make test` 原样命令**：本机无 `make`（台账 P4 同一条），只能跑等价单命令。
4. **KS 侧端到端**：F8 只证明了调用形状（shim → 内核类），没跑过 KS 的真实会话历史路径。

**§8.1 误判风险的缓解（不需要新决策，落地即带）**：env 显式可覆盖 + 降级时 `logger.warning` 带原异常（F4 的 :112）⇒
真出现"2s 判宕"时，运维侧有一条可读证据链和一个不改代码的处置（把值调大），而不是只能改代码重发版。

---

## 9. 排除项（逐项理由 + 复审触发条件，不写触发条件的排除项等于没排除）

| 排除 | 理由 | 复审触发条件 |
|---|---|---|
| `/health` 上报 checkpointer/mongo 真实装配态（F12：降级现在不可见） | 它是**可观测面**问题，不是超时问题；且 `health_router.py:66-72` 已有 `enabled/ready` 成对先例，而「三套 status 约定是否统一」在 `CHANGELOG.md:28` 里仍是待拍板项 ⇒ 塞进本批会把一个 D2 混进 D1 | 本批落地后需登记它。本文**不代登**：台账 §3 那句「只留卡住判定的八项」是一条计数，加一行就得连带改它；而本项**不卡住 D27 施工**，按该表的收录口径它更适合进 `docs/TODO.md` 排期 —— **已定（2026-10-30 用户答复批）：进 `docs/TODO.md` §6（末条）+ 配套 §0.2 第 5 行，不入本台账 §3**（同批把 `scripts/evidence/recount_todo_index.py` 的 `DECLARED_TOTAL` 随动为 open 26 / closed 24，实跑 PASS）。⇒ 本行不再是「待登记」，复审触发条件改：**要动 `/health` 契约时**（前置仍是「三套 `status` 约定是否统一」，`CHANGELOG.md:28`） |
| `socketTimeoutMS` / `connectTimeoutMS` | 改它们等于改"已在跑的读写何时被杀"，语义风险远大于 F5 那条已定位的 30s；本批只收 server selection 这一笔 | 现网出现请求挂死 / 无响应超 connect 超时；或有人立项统一三类超时 |
| `MONGO_*` 全族裸读收敛（`memory/__init__.py:94/103/104-106/107` 四处都是裸读 `MONGO_URL` / `MONGO_DB` / `MONGO_CHECKPOINT_COLLECTION` / `TENANT_ID`） | P14 ② 的口径是**按命名空间**禁（`CACHE_*`），照搬到 `MONGO_*` 会连带 6 个应用与 KS 的 pydantic-settings 家法（两套配置形状不同）⇒ 影响面从 1 个文件涨到跨包重构 | 下一次做 WS-5（`agent_core.config` env 集中化）续批时；或 P15 ② 出现第一处真实违规时 |
| KS 的 `Minio(`（`clients/minio_utils.py:14`）与 `MilvusClient(uri=...)`（`clients/milvus_utils.py:26`）同族形状 | **本轮未测它们的探活代价**，没有读数就没有默认值；把它们写进"顺手一起改"是拿未验证事实排期 | 任一同类出现"无该依赖时门禁墙钟/首请求被拖住"的实测；届时工厂可扩为 `is_reachable` 的同族第二实现 |
| `create_index` 搬进工厂（R6） | F5 的 C 探量已证明慢不在它 | 出现"索引创建本身慢/失败语义要统一"的证据 |
| `resilience.timeout` 装饰器方案 | 取证 §5.1 末已排除并留字：线程池包装 + `shutdown(wait=False)`（`agent_core/resilience.py:200,222`）**不取消底层调用**，而构造又是惰性的（D 探量 0.00s）⇒ 装饰构造无效，装饰首个操作只是把等待方换成 `TimeoutError` | 有人重写 `resilience` 的超时原语（台账 D27 复审条件同一条） |

---

## 10. 拍板与施工授权是两件事

- 本文**已定的**：收敛层级（共享包）、模块形状、三条 lint 判据、warn+回退 vs 抛错的家法取舍、5 步顺序、排除面。实现者不需要再做选择。
- 本文**曾欠你一个答复的**：默认值 `2000`（§3 末，D1——可逆但属对外承诺）⇒ **2026-10-30 已确认**，本文不再有欠答项。
- 本文**没有做的**：没动任何产品代码、没建 lint 规则、没改 README/ARCHITECTURE 的计数。
  S1 之前一行代码不写；你说"开工"我才按 S1→S2→S3→S4 逐批提交，S5 另等环境放行。
- **排期已定 ≠ 授权已定**（2026-10-30 答复批）：用户把 D27 排在**前端之后**——这是顺序指示，不是 S1 的开工许可。到窗口后仍需一次显式"开工"，我才会新建 `mongo_client.py`。
