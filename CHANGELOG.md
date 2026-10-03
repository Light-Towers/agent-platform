# Changelog

本仓库为 uv workspace monorepo。**唯一受支持的安装/运行入口是根 `uv.lock` + `uv sync`**，子包不再维护独立 `uv.lock`（见 v2 修复 #14）。

## 审计主体去凭据化（实施）：`operator` 改服务端断言租户 + 新 **P12** 门禁 + ks shim 契约用例（2026-10-03，单 PR）

> 承接下一段（同日的只读审计 + 方案）。Q1–Q4 已拍板「按建议四项全部实施」，ks 守卫用例「落」。方案：`docs/plans/plan-audit-operator-principal-2026-10-03.md`。**测量时点：HEAD `ffd86ab` 之上的本工作树（未 commit），extras 形态两种都实跑**（见「验证」条）。

### 1. 代码改动（4 文件，均产品代码；schema 不变、无 migration）

- `applications/agent_server/api/session_router.py`：`operator = api_key or "default"` → **`operator = server_tenant_id(settings.default_tenant_id)`**，并新增函数 docstring 写明「`verify_api_key` 返回入站头**原文**（不是摘要），把它当 `operator` 等于把部署密钥持久化进审计痕迹」；`_auth=Depends(verify_api_key)`（形参不再叫 `api_key`）；新增 `from agent_runtime.workspace_registry import server_tenant_id`（依赖方向 app → agent-runtime，红线 1 合规）。值形状选 (a) 租户原值（Q1），与仓内 7 处既有写法同构；ContextVar 绑定时**请求租户优先**（与 `/import`、`/sql/train` 同语义，有用例锁）。
- `api/import_router.py:28`、`api/sql_router.py:21`：两处**死凭据绑定**改 `_auth=`（FastAPI 的 `Depends` 只认 callable，形参名不参与解析 ⇒ 鉴权行为逐字不变）。收益是 P12 可以**零白名单**落地（不必给「绑了但没用」开后门）。
- `scripts/lint_architecture.py` 新增 **P12**（`main()` 内接 `v14`）：AST 判据——凡形参默认值为 `Depends(<在册凭据依赖>)` / `Security(...)` 者，该形参名不得作为**任何 `Call` 的实参**（位置或关键字）出现在函数体内（含内层闭包）；作用域 `applications/**`，**无白名单**，fail-closed（解析不了即判违规，与 P11 同口径）。`_CREDENTIAL_DEPS` 现为 `("verify_api_key",)`。
- 登记位：`ARCHITECTURE.md` §4.1 门禁登记表新增 P12 行（含「名匹配粗筛、不得当全局完备门禁」的局限句）。

### 2. 本条是这批最重要的一条：P12 首跑报红，红的是**我自己实现的假阳性**

首次实跑 `lint_architecture.py`（rc=1）报出的**不是**预期外流违规，而是 10 条 `无法解析（invalid non-printable character U+FEFF）`——`applications/nl2sql-service/nl2sql_service/**/__init__.py` **带 UTF-8 BOM 且已入库**（逐字节实取：全仓 `.py` 恰 10 个，全在此包），而我的 fail-closed 用 `read_text(encoding="utf-8")` + `ast.parse`。Python 自己的源码加载器会剥 BOM（PEP 263）⇒ 这些文件 import 一直正常，**BOM 从来不是缺陷，是我的读取编码不对**。已改 `utf-8-sig` 并在注释写明理由：

- **为什么不能就这么算了**：fail-closed 的价值在于「真解析不了必报」，而假阳性会把门禁的第一批用户训练成「改宽它」——那才是破窗的开始。修的是读取约定，**不是**判定强度：语法真坏仍报（新增用例锁），BOM 文件里的真外流仍报（新增 BOM 回归锁）。
- **顺带登记（不属本批、未动）**：这 10 个 BOM 文件是否统一改无 BOM 另属编码规范议题，本批只保证 lint 不被它误伤。
- **另一条度量**：`lint_architecture.py` 单跑实测 **253s**（全仓 rglob + AST）。此前一轮「前台 rc=124 无输出」是**工具默认 180s 超时**，不是脚本异常；按 testing-playbook §2「静默不执行须以产物核实」改后台落盘才拿到结果。

### 3. 三层齐备的②③层：新增用例 37 条

- `tests/governance/test_audit_operator_principal.py` **29 条**（实测全绿）：行为面（`operator == server_tenant_id(default_tenant_id)`、ContextVar 优先、入站密钥值不进任何 `caplog` 记录、审计原语 `revert_audit` 行只带身份）+ 签名面（三处站点凭据形参在函数体内**完全不被引用**，比 P12 的「不当实参」更严）+ 门禁面（`_is_credential_dep` 八例分类、defaults 右对齐、四种外流形状、绑定本身不算外流、**已知盲区 `return` 显式写红为「不是免死牌」**、真实树零违规、`applications/` 外不扫、合成一坏一好、fail-closed、BOM 回归锁、**剥掉真实 `session_router` 防线必判红**的回归锁）。
- `applications/knowledge-service/tests/unit/test_tracing_reset_hook_contract.py` **8 条**（上一段登记的防复发项落地）：钉 kernel `__all__` 含私有名 `_reset_for_tests`、shim 解析到的是 kernel **同一对象**、钩子可重复调用、shim 的 `import *` 仍在（结构早警）、消费方 `test_tracing.py::_reset_tracing` 确实还在用它、外加三条公共面兜住。**这条把「15 个莫名 setup error」变成「一条直白的红」**。
- 未删用例、未收窄断言、未放宽前置；未引入任何 dismiss。

### 4. 验证（最终树重跑，命令逐条对齐 Makefile `test`；extras 形态两种都跑）

| 项 | 结果 |
|---|---|
| `lint_architecture.py` | **rc=0**，14 条门禁全过（含 P12「无『凭据绑定形参值被当作实参外流』的站点」），单跑 253s |
| `ruff check .` | rc=0（首跑报出 **2 条我自己的** I001 import 排序，已 `--fix` 后在最终树复跑） |
| `check_doc_sync.py` | rc=0（0 警告） |
| 根 session `pytest -q -m "not requires_pg"` | **964 passed / 8 skipped / 28 deselected**（基线 935 → **+29 = 恰为本批新文件**） |
| `packages/agent-runtime/tests` | 594 passed / 1 skipped（`test_revert.py` 传字面 `operator="test_user"`，断言方向未动） |
| `applications/agent_server/tests` | 44 passed |
| knowledge-service **SDK 在场** | **410 passed / 7 skipped**（= 基线 402 + 新契约 8） |
| knowledge-service **SDK 不在场**（`uv sync --all-packages --extra dev` 后） | **404 passed / 13 skipped**（= 基线 396 + 新契约 8）⇒ 契约用例与 extras 形态无关，docstring 的承诺有实测支撑 |
| 形态复原 | `uv run --extra otel pytest tests/observability` 15 passed，复跑 ks 回到 410/7 |

### 5. 验收对照与未闭合项（不美化）

- 方案 §6 判据 1–5 **本地已达**；判据 1 的表述按实取订正：`git grep "operator = api_key"` 在**码面** 0 命中，唯一命中是 lint docstring 里引着旧形状的那句说明；`session_router.py` 剩余的 `api_key` 字样只有 import 的 `verify_api_key`（依赖本体）与 docstring 叙述，**无任何名为 `api_key` 的形参**。另实取全 `applications/**` 已无 `api_key=Depends` 残留（0 命中）。
- 判据 6「主干面」与判据 7 的 commit/PR **尚未执行**：本批只到「本地最终树全绿 + 账面入库」，合入后 `refs/heads/main` 重扫 open=0/dismissed=0 不回退仍待取（PR 绿 ≠ 主干绿）。
- **P12 不得被汇报成「凭据不入审计已有全局完备门禁」**：名匹配抓不到别名间接流（本项缺陷本身就是人工发现的）、抓不到 `return` 等外流形状，kernel 侧归 P6。
- 部署侧存量 `revert_audit.operator` 历史行**仍未取证**（本机三条通道不通），代跑命令在 `docs/operations/audit-operator-principal-runbook.md`；旧审计行**不自动改写**（Q3 拍板 (a)：不静默销毁痕迹）。
- ks 一次性 15 errors **本批未定性为已解释**：它仍未再现（现累计 2×10 session 批量 + 5 次 ks 单 session + 契约用例两种形态各 1 次），本批落的是「再发生时立刻指向契约」的守卫，不是根因结论。

## B7b 收尾衍生项：审计主体去凭据化（只立方案）+ ks 一次性 15 errors 定性 + 部署侧取证 runbook（**纯取证/文档，未动一行产品代码**，2026-10-03）

> 来源：`docs/TODO.md` §5 三条尾项 + §8 两项未取证。**测量时点**：HEAD `ffd86ab`（工作区仅本段新增两份 docs），ks 计数均为 **OTel SDK 在场形态**（见下「extras 形态」条）。

### 1. 会话回退审计把凭据当主体（`session_router.py`）——审计闭合 + 方案已立，**待拍板后才动码**

- **缺陷链实取**：`api/auth.py:23` `verify_api_key` **返回入站头原文**（不是摘要）⇒ `session_router.py:57` `operator = api_key or "default"` 是**明文部署密钥** ⇒ 两条出口均落该值：PG 模式 `revert.py:131` `INSERT INTO revert_audit(..., operator, ...)`，内存模式 `revert.py:148` `logger.info("revert_audit ... operator=%s ...")`，两者均在 `spawn_background` 异步执行。表 DDL 在 `packages/agent-runtime/agent_runtime/migrations/001_baseline.up.sql:85-95`（`operator TEXT NOT NULL` + `idx_revert_operator`）。
- **消费者审计（TODO 原定的动工前置）**：全仓 `SELECT ... FROM revert_audit` **0 处** ⇒ write-only 列，无前端/无对外 API ⇒ 换值不破已知消费者。基数等价论证（与 B7b-4 §3.4 同构）：`API_KEY` 每部署一把 ⇒「按密钥区分操作人」今天本就区分不出任何两个调用方，换租户主体**基数不变（仍是 1）**。
- **为何 CodeQL 未报**（登记以免后人误读为「扫描器看过且认为没问题」）：`py/clear-text-logging-sensitive-data` 依赖数据流将值分类为 secret，而此处凭据经由 app → runtime 的形参 `operator`（两个模块之间的传递）传入，未被接到流上 ⇒ **未报出 ≠ 不存在**，本项由人工语义审计发现。
- **额外扫出两处死凭据绑定**：`api/import_router.py:28` 与 `api/sql_router.py:21` 的 `api_key=Depends(verify_api_key)` 函数体从不使用（全仓 `Depends(verify_api_key)` 共 5 处，其余 2 处已是 `_auth=` 形态）⇒ 改形参名即**签名级**去掉凭据可见性（FastAPI 只认 callable，零行为变更）。
- **方案**：`docs/plans/plan-audit-operator-principal-2026-10-03.md`——选型 A（`operator = server_tenant_id(get_settings().default_tenant_id)`，与仓内 7 处既有写法同构）、单 PR 实施步骤（含新增 **P12** lint 不变量：`Depends(verify_api_key)` 绑定的形参名不得作为任何 Call 的实参，并写破「名匹配抓不到别名间接流」的局限）、迁移与旧行处置（**不自动改写审计痕迹**，只给可选脱敏 SQL + 用 `reverted_at < 升级时刻` 判别新旧）、7 条验收硬指标（含「PR 绿 ≠ 主干绿，合入后 `refs/heads/main` 重扫 open=0/dismissed=0 不回退」）、Q1–Q4 待拍板项。

### 2. ks session 一次性 15 errors：从「无从定性」推到「唯一候选站点 + 机理自洽」

方法和实测结果已入 `docs/operations/testing-playbook.md` §2.3（三步法），此处只记结论：

- **计数算术**：`--collect-only -q` 实取 collected = **409**；历史红为 `387 + 7 + 15 = 409`，全绿为 `402 + 7 = 409` ⇒ 集合未变，形态是「恰好 15 条在 **setup 阶段 error**」，而非集合/收集变化。
- **唯一候选**：按文件分组实取，ks 全 suite **唯一**恰含 15 条用例的文件 = `applications/knowledge-service/tests/unit/test_tracing.py`，15 条共用同一个 autouse fixture `_reset_tracing`（前后各调 `tracing._reset_for_tests()`）⇒ 该 fixture 抛错能**精确**重现现场签名（15 errors + 其余全过 + skip 数不变）。
- **两条关键实测（不凭记忆）**：① 探针（抛错的 autouse fixture + 一条 `skipif` 用例）得 `1 skipped, 2 errors` ⇒ **`skipif` 判定早于 fixture**；② `uv sync --all-packages --extra dev`（= `make install`）**会就地卸载 10 个 `opentelemetry-*` 包**（dry-run 先报 `Would uninstall 10 packages`），实测两形态计数：SDK 在场 `402/7`・该文件 `15 passed`；SDK 不在场 `396/13`・该文件 `9 passed + 6 skipped`（已按原状恢复并复核）。
- **【账面订正，本段最重要一条】「CI 也绿」不能用作排除证据**：由 ①+② 得，CI（`make install` 后跑 ks，SDK 不在场）该文件**最多只能报 9 errors** ⇒ `15 errors` 这一签名**只在真 SDK 在场的本地 venv 才可能存在**，CI 跑的是与现场不同构的另一种形态。原 `docs/TODO.md` §5 追记把「PR #58 与主干 `cf73396` 的 ci 均 pass」当作「未复现」的加重证据，论证强度已被本条订正（追记就地订正为引用本实测）。
- **未定项诚实登记**：kernel `agent_core/tracing.py:603` `_reset_for_tests` 的每步危险操作都被 `try/except` 包裹 ⇒ 自身几乎不可能抛；最可能破点是 `tracing._reset_for_tests` 的**名字解析**（kernel `__all__` 显式包含该私有名 + shim `import *` 这条链条**全仓无用例钉住**）；并发 `uv sync` 就地删装包文件与「一次性/不可复现」自洽，但**无现场证据**，只登记为假设。**定案仍需一次带 traceback 的再现**，本轮 2×10 session 批量全量日志（完整落盘）+ 4 次 ks 单 session + 1 次单文件均未再现。
- **新登记的防复发项（属测试面，按红线先立项再动）**：给 ks shim 加一条守卫用例（`from knowledge_service.core import tracing` 必须解析得到 `_reset_for_tests`），把这类失败从「15 个莫名 error」变成「一条清晰的红」。

### 3. 采样与部署侧环境取证（c4/c5）

- **采样**（均 `rc=0`）：2 轮 10-session 批量（`sessions-b1` / `sessions-b2` 全量日志，root `935 passed / 8 skipped / 28 deselected`、agent-runtime `594/1`、exhibition `348`、ks `402/7`、observability-otel `15`）+ 4 次 ks 单 session 重复采样。
- **本机无 docker / kubectl / podman / `.env` / `~/.kube/config`**；`root@192.168.100.126:22` 单次再试仍为 `Connection closed by ... port 22`（rc=255，与前四次同签名）⇒ **部署侧与 `tests/ha` 本机无法补跑**；`tests/ha` 真 PG 结果已由 CI run `37096026471`（`ha.yml`）承担。
- **转为可代跑 runbook**：新建 `docs/operations/audit-operator-principal-runbook.md`（全程只读、输出不落敏感原值；取证 A = 存量 `user-*` thread_id，取证 B = `revert_audit.operator` 历史行形态；三选一解阻通道）。等值判定采「本地算 md5 后作为等值连接子传入」，**不把密钥送进 SQL 会话**。
- **包装脚本两条自纠（同类假阴 bug 第二次）**：`_SUMMARY_RE` 只认 `=+ ... =+` 形态，而 `-q` 摘要行无装饰 ⇒ 每次正常跑都误报「无 pytest 摘要行」；改正则后又漏 `re.M`（`^`/`$` 只锚整串首尾）。两处均已就地修并写成注释防后人改回；另修正一个错字。上一段登记的后台批量跑「静默未执行」已用「预期产物文件是否生成」核实并重新拉起（testing-playbook §2 明文纪律）。

### 4. 文档面变更清单

新建：`docs/plans/plan-audit-operator-principal-2026-10-03.md`、`docs/operations/audit-operator-principal-runbook.md`。修改：`docs/operations/testing-playbook.md`（新增 §2.2 extras 形态、§2.3 计数算术三步法）、`docs/TODO.md`（§5 三条：15 errors 二次追记 + 计数时点项转 `[x]` + operator 项挂方案；§8 部署项挂 runbook）。**产品代码/测试代码零改动**（已 `git status --short` 核实：无 `.py` 文件在改动面内，仅本段列出的文档）。本轮编码校验改用 Python 脚本（`.codeartsdoer/temp/scan_mojibake.py`，显式按 UTF-8 解码 + 逐字符判定）：5 份文档共命中 2 行，**均为自命中**（命中行就是把扫描模式原样写进账里的那句），无真乱码。【工具链教训】旧写法 `git grep -I -c -e 锟 …` 在 PowerShell 下会因码页转换把多字节模式搞成“几乎每行都命中”的假阳性（本轮实测：三个文件各报 694/104/124 条），**不得再用它做中文乱码判定**；而脚本扫描的命中行也要回看内容，因为扫描字串本身常被写进文档。

## B7b 尾项：identity 中间件 flaky 用例定性并修复（仅测试代码，2026-10-03）

> 来源：`docs/TODO.md` §5 登记的「1/256 概率假失败」，修法当时已定型（不属 `#38`/`#39` 通路，故 B7b 主批为不扩大爆炸半径而未动）。

- **根因**：`test_forged_internal_header_rejected` 用 `val[:-2] + "ff"` 构造伪造内部头，而签名 = HMAC(含时间戳的 payload) 每秒一变 ⇒ 真签名末尾恰为 `ff` 时伪造串 == 合法串，中间件正确返 200，用例断 401 就假失败。
- **改法**：末尾 hex 换成 `"11" if val.endswith("00") else "00"`，并加前置断言「伪造串必与合法串不同」。只破坏签名尾部、payload 与格式保持合法 ⇒ 401 仍必须来自**签名校验**而非格式报错；未删用例、未收窄断言。
- **穷举证明**：对 256 种签名末尾取值全枚举，旧写法有 1 种（`ff`）使 `forged == val`，新写法 **0 种**。
- **实跑**（计数附测量时点：在 commit 本身上重跑，非中间工作态）：`test_identity_middleware.py` **11 passed**；agent-runtime session **594 passed / 1 skipped**。CI（Linux）为权威判据。

## B7b-4 + B7b-5 实施：链① 会话身份主体化（PR-A）+ 死代码/门禁/文档收口（PR-B）（2026-10-02）

> 类型：产品代码变更（安全契约）+ 迁移脚本重写 + 门禁换代 + 文档同步。方案：`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md`（§8 三项已拍板；§9 取证受阻的**实施后记已就地补在彼处**）。闭合目标：`#38`（链①）、`#39`（`legacy_thread_id`）。硬约束（继承用户定调）：**不引入任何 `false_positive`/`wont_fix`**，只认 `state=fixed` 且 `dismissed_at`/`dismissed_by`/`dismissal_reasons` 全 `None`；不换 scrypt/pbkdf2（能消警但按错误前提付热路径延迟）；不靠改名躲启发式（分类由名字驱动，改名即 gaming）。

### PR-A：会话身份主体化（拆链①）

- **做了什么（kernel）**：`guardrails/auth.py` 新增 `resolve_thread_identity(principal)`——产物 `f"{THREAD_ID_PREFIX}{principal}"`，**不做任何摘要**（租户 id 本身即可入目录名）。两条 fail-fast：空/全空白即 `ValueError`（静默兜底 = 跨租户串会话）；主体必落 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`。后者不是装饰：实取 `guardrails/fs.py` 白名单为 `[^\w.\- ]`，`:``/``\``*``?` 等一律被洗成 `_` ⇒ 若内核做清洗，租户 `a:b` 与 `a_b` 会落同一目录，而迁移的「目标已存在拒覆盖」会把这种配置误判成碰撞——**内核不做有损清洗（清洗 = 制造碰撞面）**，非 ASCII/含分隔符的 id 由宿主显式提供 filename-safe slug。主体兜底策略留在宿主层，kernel 保持零依赖（红线 1）。
- **前缀由 `user-` 改 `tenant-`（与 B7b-5 同批，否则二次迁移）**：三条理由按档级排——① **数据面可分性**（决定判据能否退化成正则）：同为 `user-` 前缀时，若某租户 id 恰为 12/32 位十六进制串，新旧行在库内**完全不可区分**；换前缀后待迁移集合精确等于「两代凭据摘要形态」。② `user-` 是 overloaded 命名空间（实取 `agent_federation/api/monitor.py` `build_thread_id()` 的 `user-<uid>-session-<sid>` 兼容符号 + dev 模式客户端可自填）。③ 语义诚实：主体已定为租户，`user-` 名不副实（与本批「不为消警而 gaming」同源）。代价不当无副作用写破：会话 id 对外形态**第三次**变更（`user-<12hex>` → `user-<32hex>` → `tenant-<id>`），故兼容窗口与迁移必须同批交接。
- **两个 app 签名级去凭据位**：`resolve_thread_id(client_thread_id)` **删掉 `api_key`/`api_key_header` 形参**（与 B7b-2 同构——留着形参就是留着缺口，CodeQL 的 Expensive 分支把**形参名即视为 password 源**）。agent_server 启用鉴权分支走 `resolve_thread_identity(server_tenant_id(get_settings().default_tenant_id))`（与 `import_router`/`sql_router`/`capabilities` 既有写法一致：ContextVar 断言优先，其次部署级 default）；**开发模式分支逐字不变**。`verify_api_key` 返回值仅作鉴权用途，不再参与身份派生；**不得**用 `req.tenant_id`（客户端可传 = 会话劫持回归）。
- **联邦侧两个维度正交，不得合并成一条链**（原方案 §4.1/§6 混处的地方）：维度一「是否启用鉴权」决定**信任谁**（`API_KEY` 为空 ⇒ 一律 `client_thread_id or DEV_THREAD_ID`，逐字维持现状，三态完全不参与此分支）；维度二「主体来源三态」只在鉴权启用时求值：断言 ContextVar → `resolve_startup_tenant_mode()` 的 `single` → insecure（`DEPLOY_ENFORCE_IDENTITY=true` 抛 `PrincipalUndetermined` 由调用方兜为 401；未开启则退 `DEV_THREAD_ID` + **warn-once**）。**必须写破的等价性**：insecure→`DEV_THREAD_ID` 不砍 dev 多会话能力（那条能力活在维度一），与今天「同密钥共用一桶」相比**桶数不变（仍是 1）**，变的只是 id 形态；若把两维误合并（insecure 时无条件退共享桶），才会静默砍掉联调能力 ⇒ 用例双向锁住这两条。
- **接线序对调（联邦，可独立回滚的最后一个 commit）**：`mount_identity_middleware(app)` 移到 `SecurityGuardsMiddleware` 注册**之后**（Starlette `add_middleware` 做 `insert(0, …)` ⇒ 后注册者更外层），并给 guards 传 `subject_provider=get_asserted_tenant_context`。修的是 B7b-2 登记的中间态：旧序下 guards 更外层、执行时租户尚未绑定 ⇒ **限流桶实为 IP 兜底**。行为变更写明并锁住：**伪造/过期 `X-Tenant-JWT` 的 401 会抢在 API-Key 401 之前**。
- **迁移脚本改枚举式**（因删 `derive_thread_id` 而被迫同批）：`--api-key` → `--principal`（空则 `exit 2`），导入仅剩 `resolve_thread_identity`，**脚本内零 hashlib/hmac**（AST 用例锁）。判别式：`^user-[0-9a-f]{12}$`（48bit legacy）或 `^user-[0-9a-f]{32}$`（128bit），两代都是凭据派生都要重挂；`user-` 开头但不命中正则的**一律不动并列入人工核实**（实取两类来源：`monitor.build_thread_id()` 兼容形式、dev 自填如 `user-x`）。DB 侧：PG 的 `LIKE` 不认正则 ⇒ `LIKE 'user-%'` 取候选 + Python 侧正则定案（宁可多捞再筛），只**打印**三张 checkpoint 表的绑定变量 `UPDATE`、**不代执行**（沿用现脚本「CI 无 PG 故不把未验证写操作固化」的安全边界）；默认 dry-run，兼容窗口内旧目录**只读不删**。

### PR-B（=B7b-5）：退役实现 + 门禁换代 + 文档同步

- **删了全仓唯一的指纹实现**：`fingerprint` / `derive_thread_id` / `legacy_thread_id` / `ENV_SECURITY_PEPPER` / `MIN_FINGERPRINT_HEX` / `THREAD_ID_DIGEST_HEX` 及其在 `guardrails/__init__.py` 的转发导出；连带去 pepper 化（`.env.example` 段、`tests/conftest.py` 的 `_CLEARED_VARS`、agent-core README 环境变量表、TODO 部署项）。结果：**`guardrails/auth.py` 已不含 `hashlib`/`hmac` 一个字符**（不只靠人眼看）。
- **门禁换代（横切三层齐备的第三层）**：P6-1 白名单**置空**（kernel 单一实现已不存在，继续留着就是留着缺口）+ 新增 P6-3「四个已退役入口名（`fingerprint`/`derive_thread_id`/`legacy_thread_id`/`_hash_api_key`）以调用或定义形式再现即失败」，判定抽成单行函数以便反例单测（沿用 `_is_bare_secret_hash_line` 的做法）；P6-2（「弱派生只允许迁移脚本调用」）随被治理对象消失而作废。**这是「被治理对象消失 + 门禁换代」，不是删用例凑绿**：`test_p6_2_*` 的同等语义由 `test_p6_3_*` 逐条承接（正例 5 / 反例 4 / 全仓零违规 / tmp_path 三处探针无豁免位）。
- **自撞一次（新门禁立刻生效的证据）**：P6-3 首跑就报了 4 处——全在本批自己写的 docstring 里（`derive_thread_id(api_key)`、`key:{fingerprint(provided)}` 这种「名字 + 左括号」形式）。处置不是给自家开白名单，而是把文案改成不含 ASCII `name(` 的等价表述 ⇒ 门禁对所有人（包括写它的人）一致。
- **文档同步面**：`packages/agent-core/README.md`（模块表 + 环境变量表去 pepper，改成一段「为何不再登记」）、`ARCHITECTURE.md`（§2.3 全局装配补**接线序属装配语义的一部分**、B7b 关系由「不重叠」改「已合流（会话身份是本层的消费者）」、门禁表 P6/P6-2 → P6/P6-3）、`docs/TODO.md`（§5 两条新登记 + §8 部署项改枚举式运维交接）、联邦 `docs/production-action-plan.md` §1.5（本批实际落地推翻该节原拟的 `uuid5(api_key)`，就地标「不得照抄」，保留历史意图）。`docs/plans/*` 与旧 CHANGELOG 条目为历史快照，不改写（只在新段与方案尾补后记）。

### 测试（函数数相对 base `121f93e` 实取；本批落为两个 commit：主体 `55ac9f0` + 接线序对调 `1421b0f`）

`tests/governance/test_auth.py` **6 → 8**（三个 `resolve_thread_id` 用例按新契约改写 + AST 签名守门参数化两 app）、`tests/governance/test_thread_identity_migration.py` **18 → 28**（枚举判别式/人工核实/幂等/不并挂/P6-3 正反例）、`packages/agent-core/tests/test_guardrails_fingerprint.py` **17 → 13**（删 8 个指纹用例，格式/区分度用例迁给 `resolve_thread_identity`，新增字符集 fail-fast + 单射性；AST 语义门禁由 `{derive_thread_id}` 收到 `== set()` 并**扩展**为「模块内 `hashlib`/`hmac` 的 import 与属性调用为零」）、`test_llm_registry_cache.py` 11 → 11（去 pepper 依赖，断言改为穷举 6 种摘要算法 × 全量/`[:12]`/`[:32]` 的否定式，**加严非收窄**）、联邦 `tests/test_auth.py` **5 → 10**（含 insecure 三态两例 + dev 多会话双向）、`test_file_endpoints.py` 14 → 14（3 处 `monkeypatch` 改单参）；新建 `tests/unit/test_identity_guards_order.py` **8**（2 个 AST 接线序门禁 + 6 个行为用例）。

- **一条实测推翻的判据假设（自纠，写下来以免后人重踩）**：原以为「伪造 JWT + 正确 API_KEY」能区分新旧接线序。实跑发现旧序**同样**得到 identity 401（guards 虽更外层但凭据正确就放行，仍会进入内层 identity）⇒ 该组合不是判据。真正能区分的是另两条：① **两侧凭据都非法**时的 401 归属（新序 identity 先拒 / 旧序 guards 先拒）；② **合法 JWT + 正确 key 时 guards 看到的主体**（新序 `["tenantA"]` / 旧序 `[None]`，后者直接命中 B7b-2 登记的中间态）。用例已按此重构，两个方向各一个锁。

### 验证（均为本机实跑）

- 门禁：`ruff check .` `All checks passed`；`scripts/lint_architecture.py` **13 条全 rc=0**（新文案：“无裸 hashlib 作用于密钥类标识，且已退役的「凭据→摘要」入口名零再现”）；`scripts/check_doc_sync.py` **0 警告**；改动文件 `py_compile -W error::SyntaxWarning` 零告警（修过一处 `\w` docstring 转义）。
- **合入前 CodeQL pre 面基线已实取（b3 的前半，脚本 `.codeartsdoer/temp/verify_main_b7b4.py --preflight`）**：`refs/heads/main` open **恰 `[38, 39]`**；base `121f93e` 自己那条 analysis（`1880957872`，results=2）给出 2 个 sink = `auth.py:103 in fingerprint()`（#38）与 `auth.py:128 in legacy_thread_id()`（#39）；按源码文本计的通路标记命中：**链① 合计 21 处**（弱摘要 8 + 摘要位派生 13）、kernel 摘要入口 11 处、**链② 0 处** ⇒ 双向断言的 pre 侧成立（合入后取到 0 才是本批起效，而非“本来就没扫到”），且链② 在 B7b-2（`76589c4`）的闭合到当前 base **未回退**。
- **两条新踩的取证坑（已写进脚本注释）**：① analysis 按 SHA 匹配必须用**前缀**——`git rev-parse --short` 给 7 位（`121f93e`）而 API 给 40 位，旧脚本式 `[:8] == sha` 恒假，表现为“取不到 analysis”这种像是没扫描的假象；② **`gh auth status` 不可当门禁**——本机实测在 `api.github.com` 传输层 `EOF` 时它报“token is invalid”退出 1，而同一个 token 在三分钟前的调用刚成功；据此把脚本改成真实调用 + 重试，并按 stderr 把**传输失败**与**凭据失效（401/Bad credentials）**分开报出，前者退 2 且不出结论。
- **十个 pytest session 逐条对齐 Makefile `test` 目标（数字在最终 tip `1421b0f` 重取）**：根 **935 passed / 8 skipped / 28 deselected**、shared-schemas 28、agent-runtime **594 / 1 skipped**、agent_server/tests 44、联邦 **176**、kefu 43、exhibition **348 passed / 0 skipped**、knowledge-service **402 / 7 skipped**、nl2sql 18、`--extra otel tests/observability` 15；另跑两个不在 `make test` 里但本批直改的目录：`tests/governance` **266 passed**、`packages/agent-core/tests` **349 passed / 8 skipped**。启发式 eval **15/15 = 100%**。十个 session 的 rc 全为 0（唯一例外见下条）。
- **账面订正（不掩盖旧数字的错误）**：本段上一版写的「根 932 / 6 skipped」「exhibition 347/1」「knowledge-service 396/13」「agent-core 347/8」是**中间工作态**的数（当时 `test_thread_identity_migration.py` 的 P6-3 换代与 agent-core 指纹用例改写尚未全部落完），把它们当作本批结论属账面缺陷 ⇒ 现已换成在 commit 后的树上重跑一次的数字（总收集数不变，只是 skip↔pass 与新用例数发生漂移）。
- **一次性未复现的红（不得当作已验，也不得当作已排除）**：包装脚本连跑十个 session 时，knowledge-service session 报 **rc=1 / 387 passed / 7 skipped / 15 errors**；同一命令随后 **5 次独立复跑均 402 passed / 7 skipped**（含一次单文件跑）。定性线索：15 个 errored 项恰为正常应 PASS 的 unit 用例（387 + 15 = 402），且报的是 **ERROR**（fixture 装配阶段）而非 FAIL ⇒ 不像本批引入（本批未改 ks 任何文件，且 ks 的 7 个 skip 全是 `ZHIKU_INTEGRATION` 设计内守卫）；已排除环境泄漏（`powershell -File` 子进程实测无 `ZHIKU_INTEGRATION`，User/Machine 级也无）。**根因未定**，因为包装脚本只保留每 session 末 3 行 ⇒ traceback 丢失（教训已转 `docs/TODO.md` §5：验证包装必须落完整日志，否则一次性红无从定性）。CI（Linux）为本批权威判据，push 后以 `gh pr checks` 为准。
- **订正方案 A-6 给的一条命令（不可执行，不是环境问题）**：`uv run pytest tests/governance packages/agent-core/tests applications/agent_federation/tests -q` 在收集期即崩：`ValueError: Plugin already registered under a different name: …/agent_federation/tests/conftest.py=<module 'tests.conftest'>`。这正是 Makefile 注释写的拆 session 理由 ⇒ **分 session 跑是唯一正确做法**，后续接任务的人不要再试合并命令。
- **未验面（不得当作已验）**：`tests/ha`（真 PG + 真多实例）在本机被 conftest 以 `win32` 硬跳过 ⇒ 属设计意图而非失败，需时在 Linux 容器按 `docs/operations/testing-playbook.md` 最小配方补跑。
- **一次假红（与本批无关，已登记）**：`test_identity_middleware.py::test_forged_internal_header_rejected` 首次跑出 FAILED，随后 5 次全绿。根因非本批（该文件与 `identity*` 均不在本批 diff 内）：伪造方式是「把末尾 2 个 hex 换成 `ff`」，而签名 = HMAC(含时间戳的 payload)，若真签名末尾恰为 `ff` 则**伪造串 == 合法串** ⇒ 得 200 而断言 401（约 1/256）。修法与证据已入 `docs/TODO.md` §5，本批未动（不扩大爆炸半径）。

### 取证未拿到与运维交接（不得美化）

- 方案 §9 的两条部署侧核实（`updated/`/`output/` 目录 + `SELECT DISTINCT thread_id`）**至今拿不到**（126 的 22 端口在 banner 交换前被关闭；本机再确认无 `kubectl`、无 `~/.kube/config`、无 docker/`.env`，集群侧跳板在本地也不存在）。**本批的缓解不是补到数据，而是换策略**：迁移改枚举式 ⇒ 其正确性不依赖存量数量（存量为零则空转），故不再拿它当开工闸门。
- 仍属未取证的两项（已入 `docs/TODO.md` §8 运维交接项）：① 存量是否非零；② 该部署历史上是否存在过多个密钥（枚举法会把同一部署的历史多把密钥视作同一主体）。⇒ **不得表述为「迁移已验证」**；兼容窗口内旧目录只读不删，运维在可达环境先 dry-run 再定。
- 等价性两面都记账：今天 `API_KEY` 每部署一把 ⇒ 持同一密钥的客户端**本就共用一个 thread 桶**，改「按断言租户」不新增会话分裂；但旧 `user-<digest>` 会话/checkpoint **需运维执行枚举迁移后才可见**。

### 验收（已实取：PR #58 合入 merge `cf73396`@`2026-10-03T02:57:21Z`，以下均为合入后在 `refs/heads/main` 的实测值，脚本 rc=0）

**PR 面（先证「没新增债」）**：`ci` pass（3m5s）、`ha` pass、`assembly` pass、`Analyze (python)` / `Analyze (actions)` pass、`CodeQL` pass 且文案为 `No new alerts in code changed by this pull request`（annotations=0）；PR 作用域 open 告警 `refs/pull/58/merge` = 0、`refs/pull/58/head` = 0。（`Analyze (python)` 那 1 条 annotation 是 GitHub runner 镜像迁移提示 `ubuntu-latest` → Ubuntu 26 on 2026-10-19，与本批无关。）

**主干面（逐条对应原先写下的判据）**：

| 判据 | 实取结果 |
|---|---|
| `#38` | `state=fixed`、`fixed_at=2026-10-03T02:58:40Z`、`dismissed_at`/`dismissed_by`/`dismissal_reasons` **全 `None`**、`closed_at=None` ⇒ 自动闭合而非人工 |
| `#39` | 同上（`fixed_at` 同一时刻）|
| 主干 `state=open` | **0 条**（合入前为 `[38, 39]`）|
| 主干 `state=dismissed` | **0 条**（本批未用任何 dismiss，得证）|
| 链① 具名节点（post）| **0 处**；merge commit 自己的 analysis `1884785964` **`results_count=0`** ⇒ 整条规则在主干不再报任何 sink |
| 链① 具名节点（pre，双向断言）| base `121f93e` 的 analysis `1880957872`：**21 处**（弱摘要 8 + 摘要位派生 13）+ kernel 摘要入口 11 处 ⇒ post 的 0 具证明力 |
| 链②/链③ 不回升 | post 均 **0 处**（pre 面链② 也已为 0，属 B7b-2 已断链的正常态）|
| 最大告警号 | **48**（基线 48，不增）；合入时刻后新建告警 **0 条** |
| 仓级可复跑判据 | `git grep -nE "hashlib\.|hmac\." packages/agent-core/agent_core/guardrails/auth.py` ⇒ **零命中** |

- **重扫时序**：合入 `02:57:21Z` → 主干 analysis 落地 `02:58:40Z`（差 79 秒），告警 `fixed_at` 与之同刻 ⇒ 本仓本轮不需长时间等待；但「先确认 merge commit 自己的 analysis 存在」仍是必需步骤。
- **退役名在 kernel 里仍可 grep 到 3 处**（`auth.py:17/28/61`）——全在解释「为何删掉它」的 docstring 散文里，不含 `name(` 形式 ⇒ 与 P6-3 门禁一致。后人若只 grep 名字会误判「没删干净」，故在此留标。
- **复验脚本自纠两个自己写的假阴性守卫**（都是会让成功被判成失败的形状）：① 首版拿 `completed_at` 当「扫描是否落地」信号——**该 API 根本没有这个字段**（keys 实测只有 `created_at`/`error`/`sarif_id`/`results_count`/`rules_count`…），连早已跑完的 pre 面也报 `None` ⇒ 改为 `error is None` + `sarif_id` 存在；② 拿 `results_count > 0` 筛选 analysis——而「合入后零结果」正是要的成功态，该筛选会过滤掉 merge commit 自己那条 ⇒ 改为按 `results_count` 降序取首条并区分报告。
- **ks 一次性 15 errors 在 CI（Linux）未复现**：主干 push 的 `ci` 为 `pass`（含 knowledge-service session）⇒ 仍维持「不复现、根因未定」的记录，**不升级为「环境问题」结论**（本地 5 次 + CI 1 次均绿只排除不了什么，只能说明未再现）。
- **仍未取证（不得美化）**：部署侧会话存量迁移仍属运维交接项（见上节），告警闭合不等于迁移已完成。

## 分支处置收尾：PR #53/#54/#56 落账、7 条 ref 删除清零、pypdf 8 条 high 告警主干闭合（2026-10-02）

> 类型：纯治理/卫生（零产品源码改动；依赖版本变更由 PR #51 单独承载）。台账：`docs/plans/plan-branch-disposition-2026-10-01.md` **§9**（本轮全部取证与判据订正均在彼处）。

- **收尾登记先落账再执行**：台账新增 §9，§2/§4 补终态指针（它们列的两条已删 ref、一条已被 `--prune` 回收的 dependabot 旧分支均属历史快照，不能拿来做减法）。`docs/pr50-merge-closeout` @ `a98f0fa` → **PR #53**（11:06:58Z 合入，新 tip `63a8f23`），零漂移仍用树 OID 直比（`a98f0fa^{tree}` == `63a8f23^{tree}` = `aacee653…`）。同一 tip 主干 CodeQL 复验 PASS：open 恰 `#38`/`#39`、实例 sha = `63a8f239…`、`fixed` 44 / `dismissed` 0 / max 48 / 新建 0。
- **陷阱六（本轮新得，已入台账 §9.2）：「主干应有的门禁集合」不能当常量**。沿用 §8 的 5 条常量集去验收文档批次会报假 FAIL：`ha` / `assembly` 两个 workflow 的 `push:` 都带 `paths:` 白名单且不含 `docs/**`。交叉验证而非推断：`actions/workflows/{ha,ha-assembly}.yml/runs?head_sha=63a8f23` 均 `total_count=0`，而 `617cbf2`（含代码）各为 1。⇒ 预期集改为按本批 `git diff --name-only` 对过滤器求交派生，并要求「被过滤掉的门禁必须再用 workflow-runs API 证明确实 0 run」。正向镜像也已坐实：PR #51 只动 `pyproject.toml`/`uv.lock` ⇒ 两个过滤器同时命中 ⇒ 预期集自动变 5 条且实跑 5 条齐。
- **4 条 ref 已删（本地+远端）**：`test/rag-route-ablation-eval` `4cffe7c`、`feat/isolation-hardening` `d078312`、`feat/execution-memory-kernel-onto-main` `f459693`、`feat/observability-eval-onto-main` `afc738a`。删除器内置四重 fail-closed 安全阀（祖先 / `cherry` 无 `+` / 本地=远端=预期 tip / 白名单外不碰），本地用 `-d` 而非 `-D`；**可恢复性已证**：四个 tip 删后仍为 `origin/main` 祖先，`git branch <name> <sha>` 可原位重建（这正是「先落账再删」能成立的根）。`v3` / `v2` 按拍板保留（里程碑语义，属组织决策不是取证问题）。
- **默认分支 8 条 high 依赖告警主干闭合**（发现路径本身就是盲区信号：不是本仓门禁报的，而是 `git push --delete` 的远端回显带出的）。取证：8 条全为同一个包 `pypdf`（direct / `uv.lock`），均为解析不可信输入时的资源耗尽类，且消费面确为攻击者可控（`agent_server/api/import_router.py:59`、`agent_federation/tools/upload_file_read_tool.py:16` 均 `PdfReader(...)` 读上传件）。→ **PR #51**（`6.16.1 → 6.19.0`，11:28:03Z 合入，新 tip `baa965f`）后实测：`dependabot/alerts?state=open` = **0**，8 条均 `state=fixed` 且 `dismissal_data=null`（**未走 dismiss 通道**，重扫后 68–71 秒自动消失）；CodeQL 面零源码改动故不变。合入前按交接门禁跑了 L3 深度审查（findings=0），且**先 `gh pr checkout 51` 把待审提交纳入本地基座**，避免「审的不是即将合入的代码」式空转。
- **另一组依赖 PR 被本仓 L-4 如实拦下，且已被 Dependabot 自行关闭重开（登记为独立决策面）**：**#52**（minor-and-patch 组 14 项）的 `ci` 失败根因不是环境抖动，而是它把根 `pyproject.toml` 的 `opentelemetry-api` 抬到 `>=1.45.0`、`packages/agent-core` 仍 `>=1.24`（主干当前两处一致均 `>=1.24`），违反 L-4「多处下界一致」。【合入 #54 前的二次实跑订正】#52 并非「保持 open 等 review」：`issues/52/timeline` 的 `closed` 事件 actor = **`dependabot[bot]`（type=Bot）**、`closed_at=11:59:36Z`、`merged=false`，bot 留言 "Looks like these dependencies are updatable in another way, so this is no longer needed."（11:59:34Z）；同一时刻它还把 pypdf 从组里摘掉并开出替代 **PR #55**（13 项，分支 `minor-and-patch-f18118ef2b`），而 #55 的 `ci` 在 12:01:16Z 以**同一条 L-4 消息**再次失败（`ha`/`assembly` pass）⇒ 拦下它的是本仓门禁而非巧合，且这条门禁连续两次生效。⇒ 后续动作不是「等 PR 变绿」，而是本仓先按 `plan-observability §3.3` 归一下界（独立决策面）。被回收的 `4aa4233` 仍可经 `refs/pull/52/head` 取回（实测存在，非祖先）。
- **又一条 API 形状伪影（同属 fail-closed 族）**：Dependabot 告警的 REST 列表无 `closed_at` 字段（那是 GraphQL 的），且 `state` 终态枚举为 **`fixed`/`dismissed`，不存在 `closed`** —— 第一版按 `state != "closed"` 断言，把 8 条正确的 `state=fixed` 全判为异常（方向是假阴性，未致误报成功）。
- **一份未跟踪草稿转为 Proposed 方案入库**：`docs/plans/plan-multi-expert-adjudication-2026-09-30.md`（269 行）随 PR #53 入库，此前全仓唯一副本只在本地。仅加一条来源标注 + 行尾 CRLF→LF，**本轮不实施**。
- **第二轮收尾（PR #54 合入 `10c8629`@12:16:55Z，台账 §9.6）**：零漂移仍用树 OID 直比（`3239a8f^{tree}` == `10c8629^{tree}` = `c68ba952…`），对前 tip 净差 3 files / +101 / −2（注意：净差删除数 **不等于**两次提交 deletions 之和，第二次提交删的是第一次刚加的行，在累积 diff 里抵消）。主干复验 PASS：派生门禁集恰三条（本批全在 docs，`ha`/`assembly` 命中空并用 workflow-runs API 证 `total_count=0`）、open 恰 `#38`/`#39`、实例 sha = `10c86292…`、`fixed` 44 / `dismissed` 0 / max 48 / 新建 0、Dependabot open 仍 0。**一条时序教训**：合入后 6 秒就复验会假 FAIL（三条 check `in_progress` + 实例仍指 `baa965f7`），等约 170s 即 PASS ⇒ 先看 `status` 再看实例 sha；`status=completed` 而实例仍旧 tip 才是真没重扫。
- **剩余 3 条 ref 已删（本地+远端，台账 §9.6）**：`docs/pr50-merge-closeout` `a98f0fa`、`docs/ref-cleanup-closeout` `3239a8f`（含收尾分支自身）、`dependabot/uv/pypdf-6.19.0` `d3cf899`（远端已由 GitHub 在 #51 合并时自动回收，只删本地）。三个 tip 删后均仍为 `origin/main` 祖先（可原位重建）。删除器比第一轮多两条阀：目标集与禁删集（`main`/`v3`/`v2`/活 dependabot 分支）求交非空即整批拒绝；先切回 `main` 并 `--ff-only`（当前分支不能自删）。**ref 面（取证时刻）：远端 4 条**（`main` `10c8629` / `v3` `26cd2fa` / `v2` `b691ff1` / `minor-and-patch-f18118ef2b` `b23269a`）**本地 2 条**（`main` / `v3`），无遗留 ref 面待办（条数不随主干前进而变，但表内 `main` 的 sha 只代表取证时刻）。
- **第三轮登记（PR #56）合入 `a53cf29`@12:37:12Z，停止规则首次执行即生效**：分支 `docs/ref-closeout-round3` @ `e521360`，零漂移仍用树 OID 直比（`e521360^{tree}` == `a53cf29^{tree}` = `0078c494…`），对前 tip 净差 3 files / +37 / −3。本次用 `gh pr merge 56 --merge --delete-branch` 一次原子完成「内容入主干」与「ref 消失」（`git fetch --prune` 回显 `[deleted] (none) -> origin/docs/ref-closeout-round3`，本地分支同批消失）⇒ 未再为「删这条登记分支」开第四轮。
- **闭合订正（本轮登记自身，台账 §9.7）：把「最新 / 最终」型 tip 指针改成「取证时刻」语义**。上一轮把 ref 面的 `main` 写成 `10c8629`，而那段文字自己经 PR #56 合入后，主干就前进了——**登记动作本身会作废登记内容里写下的 tip**，与 §9.5 「不能拿一次 `ls-remote` 快照当长期事实」同族。⇒ `docs/TODO.md` 的复验行改称「最近一次复验取证」并明写：此类指针不随每次合入追改，判据必须在待验证 tip 上重跑 `verify_main_rescan_54.py <merge_sha> <pr_number>` 才算成立。闭合态复验在 `a53cf29` 实跑 PASS（open 恰 `#38`/`#39`、实例 sha = `a53cf29c…`、`fixed` 44 / `dismissed` 0 / max 48 / 新建 0、Dependabot open 0、派生门禁集三条齐、`ha`/`assembly` 证 `total_count=0`、两条 analyses 落新 tip）；同一 tip 的 CI 全量实跑 success（run `37007777285`，12:37:15→12:40:22Z）：**十个 pytest session 逐条对齐 Makefile `test` 目标**——根 **901 passed / 2 skipped / 28 deselected**、shared-schemas 28、agent-runtime 594/1、agent_server/tests 44、联邦 163、kefu 43、exhibition 347/1、knowledge-service 396/13、nl2sql 18、`--extra otel tests/observability` 15；启发式 eval **15/15 = 100%**（与上一行的「observability 15 passed」是两个不同的 15，巧合同值，不得混为一谈）；`uv lock --check` 300 包。
- **停止规则入库（防「记录删除→再记录→再删除」的无穷回归）**：从本节起，收尾分支自身的删除由**合并动作携带**（`gh pr merge --delete-branch`），一次合并原子完成「内容入主干」与「ref 消失」，不再为删登记分支额外开一轮登记。

## 观测全局装配 + RAG 分层评测入主干（并入 `test/rag-route-ablation-eval` 全量）（2026-10-02）

> 类型：产品代码变更（观测状态机收敛为 kernel 单一实现、过渡门面退役、ks 迁统一工厂、依赖 extras 归一）+ 评测体系新增。方案：分支自带的 `docs/plans/plan-observability-global-remediation-2026-09-29.md`（S0–S5 / R1–R19）、`plan-rag-sparse-encoding-consistency-2026-09-29.md`、`plan-c2-cross-agreement-pivot-2026-09-29.md`。merge 提交 `6ee7283`（双亲 `b7448c1` + `4cffe7c`，不 rewrite 历史）。

- **台账 §3 第二条执行，且未采纳其「拆分成小 PR」的建议**：拆分的前提被实测推翻——原写「75 个独有提交……很可能同样已大面积入主干」，实际 `git cherry -v origin/main test/rag-route-ablation-eval` = **25 `+` / 0 `-`**（与 isolation 那条 8/7 分布相反，无一已等价入库），所以拆分只能减少评审面、不能减少内容量；而两条主题链在分支上交织于同一批文件（`agent_core/tracing.py` 既被观测链重写又被 `--extra otel` 评测链消费），拆开会留下「先合的一半过不了门禁」的中间态。沿用 PR #41 先例全量 merge。
- **落地内容**：观测侧——kernel `agent_core/tracing.py` 单状态机（`DISABLED`/`DEGRADED`/`ACTIVE` 三态可查，终结 R5/R9/R11 的「显式关 vs 坏了」不可区分）+ `tracing_middleware.py` 统一装配 + `agent_runtime/otel.py` 过渡门面退役（其单测迁至 kernel 与 `tests/observability`）+ ks `main.py` 迁 `build_api_app` + OTel/langfuse extras 下界归一（OTel 统一 `>=1.24`：根 `[otel]` 3 条 + agent-core `[tracing]` 2 条；langfuse 统一 `>=4.0.0`：runtime `[langfuse]` / federation `[observability]` / exhibition `[langfuse]` 三处）+ `deploy/k8s/` 真集群 traceparent 演练与验收记录。评测侧——`knowledge-service/eval` 分层体系（route ablation / `gen_golden` / `run_e2e_eval` / `compare_runs` / `make_baseline` / `meta_eval_judge`，+ 13 份新单测 + 一个已冻结的脱敏回归基准锚点）与 Makefile `eval-rag-*` 六个目标（均非 hermetic，不入 `make ci`）。
- **门禁合并是本批最需要判断力的地方**（`scripts/lint_architecture.py` 6 块冲突）：主干 P11 与分支 L-1/L-2/L-3/L-4 是**两套互不冲突的新门禁**，故双保留；以主干为基底，分支四条在 `main()` 里改接 `v10..v13`——两侧原本都用 `v6..v9` 装**不同**门禁，若让这种形状 auto-merge 通过（语法合法、ruff 不报）就会静默覆盖四条。同时 `_iter_prod_py` 改为复用主干已有的 `_skipped_rel`（单一排除面），分支 registry 里收敛前的「批 3」「C1」旧标签不带入主干。
- **`_FASTAPI_WHITELIST` 取分支收紧版（摘除 ks）**：主干版仍豁免 ks `main.py`（当时它自带 handler），分支把它摘掉是因为本批同时带来 ks 迁 `build_api_app`。这不是二选一的偏好，而是可验证的：实跑 `lint_architecture.py` 13 条全 rc=0（台账 §7 陷阱二的同类情形——一个带时间戳的「主干不采信」断言，本批反过来是「主干保留的豁免」因本批变更而作废）。
- **修一个 auto-merge 不报错的真红**（分支自带缺陷，非合并引入）：`test_init_enabled_without_endpoint_degraded` 未挂 `skipif(_SDK_AVAILABLE)`，而 kernel 的降级原因优先级为「依赖层先于配置层」，导致它在**默认 CI 环境**（无 OTel SDK）必红——分支从未开 PR，从未进过 CI。处置按红线走：不改断言、不删用例、不放宽前置，而是**把隐含前置条件显式化**（`monkeypatch` 置 `_SDK_AVAILABLE=True`）+ **新增**一条 `skipif` 用例钉住优先级，两种宿主分别实跑至全绿。详细可复跑判据已入台账 **§7 陷阱三/四**。
- **验证（均为本机实跑）**：ruff `All checks passed`；`lint_architecture.py` 13 条门禁 rc=0，并对 L-1/L-2/L-3 做**负对照**（伪造一棵目录树写三行违规）确认门禁非空转（扫 515 个生产 `.py`）；`check_doc_sync.py` 0 警告；`uv lock --check` rc=0（300 包）；`eval` 启发式 15/15 = 100%；`make test` 九个 session 全绿（根 **897 passed/6 skipped**、shared-schemas 28、agent-runtime 594/1、agent_server 44、联邦 163、kefu 43、exhibition 347/1、knowledge-service 396/13、nl2sql 18）；另对 35 个被修改的 `.py`/`.toml` 跑「顶层 `def`/`class` 重名 + `tomllib` 解析」不变量：零命中。
- **已合入主干（PR #50）**：2026-10-02T10:36:37Z 以 merge commit 方式入 `main`，新 tip `617cbf2`（双亲 `b7448c1` + `afc738a`）。GitHub 那次 merge **未引入 PR 之外的内容**：`git rev-parse "afc738a^{tree}" "617cbf2^{tree}"` 两个树 OID 全等（`05974143…`）。
- **主干 CodeQL 告警面复验 PASS（PR 绿 ≠ 主干绿，在 `refs/heads/main` 实取）**：open 恰 `#38`/`#39`（`guardrails/auth.py:103` col 47-69 / `:128` col 29-60），两条告警的 `most_recent_instance.commit_sha` 均 = `617cbf29…`（`code-scanning/analyses` 最新两条 created=`10:37:53Z`/`10:37:18Z`，晚于合入时刻 ⇒ 重扫确已发生在新 tip）；`fixed` 44 / **`dismissed` 0**；全仓最大告警号 **48** 不增；合入时刻后新建告警 **0**；主干 check-runs `ci`/`ha`/`assembly`/`Analyze (python)`/`Analyze (actions)` 全 success。本批未改 `auth.py`（`git diff b7448c1..617cbf2 -- …/auth.py` 为空），旧文档里的 `:92`/`:117` 已因 PR #49 那批加 docstring 位移 +11。同一 tip 本机快验：ruff passed、`lint_architecture.py` 13 条全 rc=0、`check_doc_sync.py` 0 警告、`eval` 15/15。
- **仍未做 / 不属于本批**（下列三项已由同日的 **PR #53 / #51 收尾批**完成，终态见顶部新段与台账 **§9**）：不碰 `docs/plans/plan-multi-expert-adjudication-2026-09-30.md`（当时为本地未跟踪、全仓零引用的 Proposed 方案草稿，其基座提交 `1aea73e`/`4278e23`/`dd76835` 已随本批进主干，但方案本身未启动 ⇒ 已拍板入库为 Proposed，本轮不实施）；不删任何 ref（五条已并入分支的逐项取证已入台账 **§8**，含新登记的**陷阱五：「分支的 PR 是否 MERGED」不能当并入判据** ⇒ 已拍板并删除其中 4 条，`v3`/`v2` 保留，见 §9.3）。

## 执行记忆内核契约 ADR-0005 T0 入主干（并入 `feat/isolation-hardening` 真独有载荷）（2026-10-02）

> 类型：产品代码变更（`agent-core` 记忆层新增契约协议）。方案：`docs/adr/0005-execution-memory-kernel-contract.md` + `docs/plans/plan-memory-hardening-2026-09-27.md`（属仓内「先方案后编码」已有的成件套件，本轮只执行台账 §3 第一条，未新增设计）。并入提交 `f666bc8`（真 merge，双亲 `aaefd1d2` + `d078312`，不 rewrite 历史）。

- **base 从 `v3` 改指 `main`，因为台账的保留理由已被现实推翻**：今日实测 `git rev-list --left-right --count origin/main...origin/v3` = **67/0**，且 `git merge-base --is-ancestor 26cd2fa origin/main` 退出码 0 ⇒ v3 已被 PR #41全量合入主干。再往 v3 开 PR 等于把活落在一条落后主干 67 个提交的 ref 上。台账 §1/§2/§3 相应断言已同日订正（它们成文于 #41 **之前**，当时均对）。
- **先分“真独有”**：`git cherry -v origin/main feat/isolation-hardening` 得 15 行，**8 个 `-` / 7 个 `+`**——那 8 条（ADR-0007 身份链）内容早已随 #41 等价入库。入主干净差因此只有 **11 files / +411 / −23**，而不是裸 `git diff` 的 36 files / +3037（后者把已等价入库的身份层也算了进来）。教训已入台账 **§7**。
- **落地内容**：`agent_core/memory/execution.py`（+109）下沉 `EpisodicStoreProtocol` / `ProceduralStoreProtocol`（`@runtime_checkable`，**仅 import stdlib + `_tenant_gate` ⇒ 无红线 1 反向依赖）；`store.CapabilityReport` 补 `supports_episodic`/`supports_procedural`/`supports_working`；`memory/__init__.py` 导出两协议；两份契约测试（kernel 零第三方依赖断言 + runtime `Pg*` isinstance 满足协议，**零基类改动**）；`audit_tenant_access.py` 真库三项修复（autocommit 防事务 aborted 连坐、防御性列探测、`sec.get('status')` KeyError 兜底）；`docs/operations/testing-playbook.md`（+78）与 AGENTS.md 指向它的新行。**ADR-0005 状态由「提案」转「采纳」**，并记「转采纳 ≠ T0–T8 全完成」（T2–T8 包括 T8 `UserSemanticStore` 仍待收口）。
- **四处冲突的取侧均有书面依据**（详见 merge 正文）：`audit_tenant_access.py` 取分支版（已先证明它是主干版严格超集：差异 +46/−9，删的 9 行全为被替换原句；解后 staged blob OID 与分支版逐字节相同 `2c139a2e`）；ks `main.py` 取主干版 import（`current_asserted_tenant` 是 B7b-2 需要的超集）；ADR-0005 与 memory-hardening 两份文档**不是二选一**——主干当时的「不采信分支 T0 声明」理由正好被本次并入抽掉，改成取分支拍板 + 保留主干来源标注 + 补一段状态转正记录，并显式记下与主干导入版的一处**实质分歧**（`UserSemanticStore` 倾向「一并收口」而拍板为「单独立项归 T8」，防下游按倾向推断已收口）。
- **挡住一个 auto-merge 不报错的真问题**：`.env.example` 的 ADR-0007 身份断言 **12 个键整块重复两份**（主干一份 + 分支一份），`merge-tree` 不报冲突。发现靠后置不变量检查（抽键名做重复计数）而非冲突标记；先确认两份 17 行逐字节全等再删第二份，去重后 `git diff --cached HEAD -- .env.example` **为空**（等于还原主干版），59 个键零重复。
- **验证（均为本机实跑，未沿用分支 09-27 旧结论）**：两份 T0 契约测试在新 base 上 5 passed；ruff `All checks passed`；`lint_architecture.py` rc=0；`check_doc_sync.py` 0 警告；pytest 四个受影响 session 全绿（agent-core 314 passed/5 skipped、agent-runtime 608 passed、根 871 passed/31 skipped、knowledge-service 241 passed/13 skipped）。未跑：联邦/kefu/exhibition/nl2sql 四个 session（本批未触及其代码路径），已由 PR 面 CI 兼顾。
- 未改 `docs/TODO.md`：该线由台账 §3 与 `plan-memory-hardening` 追踪，避免开第二处真相源。

## 分支资产台账入库 + CodeQL Batch 7 系列 9 条分支处置（2026-10-02）

> 类型：纯仓库卫生（不改任何产品代码，未跑 pytest）。方案/台账：`docs/plans/plan-branch-disposition-2026-10-01.md`。

- **先落账再删 ref**：上一轮（10-01）写成的分支处置台账**一直未提交**（仅在 `docs/plans/` 里漂着）——本轮先将其入库并追加 §6，再删分支；反序会让取证结论不可复现。
- **§6 登记本批 9 条分支的逐条并入证据**（PR #38〜#47 全部已合主干）：均 `base=main`（逐条从 PR 的 `baseRefName` 取，不假定）、`state=MERGED`、本地 tip == 远端 tip。前 8 条 `cherry + = 0` / `ahead = 0` / `merge-tree` 退出码 0（完全并入）。
- **新记一条 squash 最强判据（§5 补段）**：#45 是唯一 squash 入主干的，改用 `git rev-parse "<head>^{tree}" "<squash>^{tree}"` ——两个树 OID **完全相同**（`62fb9c1d…`），再由净差 `5 files +216/−35` 与 squash 提交逐项一致交叉验证。同时登记陷阱：squash 已并入后 `cherry +`/`ahead`/`merge-tree` 退出码**均为预期假阳性**，不得据此判“未并入”（差点误删一条真分支）。
- **处置**：删本地 + 远端上述 9 条。§2 保留的三条资产分支（`v3` / `feat/isolation-hardening` / `test/rag-route-ablation-eval`）与 §4 两条远端残余（`origin/v2`、`origin/dependabot/…` 对应 OPEN PR #26）**本轮仍未动**；§3 的三条处置路径（isolation-hardening 解冲突开 PR / ablation 拆分小 PR / v3 合流）仍待排期。

## B7b-2 实施：链② 限流桶去凭据（断言主体 → IP）（2026-10-02，PR #46）

> 方案：`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md` §4.2 / §6（B7b-1 后的第二个 PR，拆 `#38` 三条链中的第二条）。本批**不改 `fingerprint` 本体、不动链①会话身份**（那是 B7b-4）。

- **做了什么**：`guardrails/auth.resolve_client_key` 删掉 `key:{fingerprint(provided)}` 分支，新签名为 `resolve_client_key(client_host, subject=None)`，返回 `sub:<断言主体>` 或 `ip:<host>`。**不是只删分支，而是删掉 `headers`/`auth_enabled` 两个形参**——CodeQL 链②的入口恰是 `headers.get("x-api-key")` 那一句（`SensitiveGetCall`），留着形参就是留着缺口，凭据从此在类型层面进不来。
- **主体为何要注入而非自取（红线 1 的具体体现）**：`server_tenant_id()` 在 `agent-runtime/workspace_registry.py`，kernel 不得反向 import ⇒ `SecurityGuardsMiddleware` 新增构造参数 `subject_provider: Callable[[], Optional[str]]`（与既有 `error_response` 注入同构），kernel 只消费回调。
- **接线面取证：三宿主只 1 个接得上**——knowledge-service 先 `add_middleware(SecurityGuardsMiddleware)` 后 `add_middleware(TenantHeaderMiddleware)`，Starlette **后添加者更外层** ⇒ 进入限流时租户已绑定，已接 `subject_provider=current_asserted_tenant`；`agent_federation` 的 identity 在 guards **之前**添加（`api/server.py:143` vs `:148`）⇒ guards 更外层、执行时主体尚未绑定；`agent_server` 不用该中间件。⇒ 两处**今日实为 IP 兜底**，本批把联邦接线序对调归 B7b-4（对调会让身份 401 抢在 API-Key 401 之前，无现有用例覆盖 ⇒ 不在本 PR 偷改）。
- **行为代价（不当无副作用重构）**：旧实现下同一把部署级密钥的所有客户端**共用一个桶**（一个客户端打满配额→同密钥其他客户端连带 429）；改后按 IP 独立。反面是**单客户端换 IP（拨号/代理/IPv6 前缀）即可重置配额**——旧实现下无效、新实现下有效，属限流强度实质下降；缓解为已有的全局窗口（`rate_limit_global`，默认 500/60s）+ 接入后的主体桶。已列为待拍板→**已拍板（2026-10-02，方案 §8 Q4）：不恢复「每密钥配额」语义，保持现状**（若将来运维确需，用服务端可验证的**密钥 id**（非凭据摘要）另开子项）。两个方向各有用例锁住，不靠叙述。
- **测试**（实取计数，非估）：`test_guardrails.py` 22 → 22（3 个 `resolve_client_key` 用例按新契约改写：主体优先 / IP 兜底 / `ip:unknown`）、`test_guardrails_fingerprint.py` 15 → 17（删旧契约「桶键走 fingerprint」2 个，新增签名守门 + 凭据无关性（参数化 4 例）+ 主体不经摘要 + **AST 语义门禁**）、ks `test_security_guards.py` 32 → 35（单元契约改写 1 + 中间件集成 3：每 IP 独立桶 / 注入主体成桶 / provider 抛 `ValueError` 不得变 500）。**未删用例、未收窄断言**：旧 `key:` 前缀断言换新语义断言（「不含 `fingerprint(cred)` 也不含裸 `sha256(cred)`」是否定式加严）。
- **新增语义门禁（三层齐备的第三层）**：`test_only_session_identity_still_digests_credentials` 用 AST 断言 `guardrails/auth.py` 内调用 `fingerprint` 的函数集合恰为 `{derive_thread_id}`——守的是「凭据→摘要」的**语义**而非名字，改名绕过会被抓。B7b-4 拆完链①后该断言应改 `== set()`（已写在用例 docstring 里，不得删用例交差）。
- **实跑结果**（本地）：`ruff check .` exit 0；`scripts/lint_architecture.py` exit 0（P2/P4-2/P5/P6/P7-P11 全过，P6 白名单本批未动，属 B7b-5）；`scripts/check_doc_sync.py` 0 警告；定向 4 文件 **109 passed**；ks unit **236 passed / 6 skipped**；联邦 **163 passed**；根 session（`-m "not requires_pg"`，含 agent-core 全量）**867 passed / 5 skipped / 27 deselected**。（备注：P6 正则只抓 `hashlib.<algo>(` 同行共现，**抓不到** `fingerprint(api_key)` 这类走 kernel 仍摘要凭据的写法 ⇒ 本批的语义守门落在测试层，上提为仓级 lint 与否按方案 §5 在 B7b-5 一并定，不中途擅自扩面。）
- **验收预期（免得误读）**：B7b-2 单独合入**仍不会**消 `#38`——还剩链①（`derive_thread_id`，B7b-4）；闭合与否只认 `refs/heads/main` 实取（PR 绿 ≠ 主干绿）。【订正】本条原写的判据「password 分类源从 2 降为 1」**已被实测推翻**，见下两条。另按 §7.2，本 PR 必查 `gh pr checks` + CodeQL check-run annotations，防「链②拆了、派生值改投另一个 sink」（B7b-1 刚踩过一次）。
- **PR 面告警闭环（已实取，不靠推定）**：check-run `110690703578` → `conclusion=success`，`output.title` = “No new alerts in code changed by this pull request”，`output.summary` 只剩分支告警链接（**无 “New alerts” 段**），annotations 为空 ⇒ 本批**未新引入任何 sink**（与 B7b-1 初版不一样，那条是自引入 `py/clear-text-logging-sensitive-data`）。`ci` / `ha` / `assembly` / `Analyze (python|actions)` 均 pass。**主干复验待合入后另跑**（`refs=refs/heads/main`，骨架原为 `verify_main_b7d.py`，本轮重写为 `.codeartsdoer/temp/verify_main_b7b2.py`），不得拿 PR 绿当主干绿。
- **主干复验 PASS（已合入 `76589c4`，在 `refs/heads/main` 实取）**：主干 push 的 `ci`/`ha`/`assembly`/`CodeQL` 全 success；复验脚本逐判据输出 `=== 总体：PASS ===`——① open 恰为 `#38`/`#39`（均在 `auth.py`：`#38` sink `:103` col 47-69 = `fingerprint()` 的 hmac-sha256，`#39` sink `:128` col 29-60 = `legacy_thread_id()` 的 `sha256[:12]`）；② `#38` 的 4 条通路**全为链①**，含链② 具名节点（`x-api-key` / `extract_api_key_from_headers` / `key:{fingerprint`）的通路数 **1 → 0**；③ `#39` 通路 3 条形状未变（本批未动 `legacy_thread_id`，仅因上游加行位移 +11）；④ `state=dismissed` **0**、全仓最大告警号 **48** 不增、合入时刻后新建告警 **0**。⇒ `#38` 进入「只剩链①」的预期中间态，B7b-4 是闭合它的最后一个 PR。
- **自纠（本轮推翻我自己刚写下的验收判据）**：上面「password 分类源从 2 降为 1」把「**链数**」当成了「**可观测通路数**」，实测两头都不成立：① pre 面 `#38` 不是 2 条而是 **4 条**通路（单条链① 被 CodeQL 枚举为 `resolve_thread_id` 两个形参 + default `None` + `derive_thread_id` 形参共 4 个源节点）；② 拆掉整条链② 后 post 面**仍是 4 条**，通路总数完全不动。⇒ **计数判据会误报“拆了但没切到通路”**（本轮第一版脚本就据此报了假异常）。可靠判据是**节点内容**：该链特有的具名节点是否还在流图上（脚本已同时断言「post 含链② 节点 = 0」与「pre 含链② 节点 > 0」，后者防判据不咬人）。教训：**拆链验收的指标是「链的具名节点集合」，不是「流条数」**——多条链在同一 sink 聚合、单条链又会被拆成多源。
- **取证方法（定型，下次不再试错）**：`alerts` REST 的 `most_recent_instance.location` 只有 `{path,start_line,…}`，**不含 codeFlows**；通路明细需 `GET /repos/{o}/{r}/code-scanning/analyses?tool=CodeQL` 取 id（**同一 commit 有 python / actions 两条**，须过 `results_count > 0`），再 `GET …/analyses/{id}` 带 `-H "Accept: application/sarif+json"`（此时**返回体本身就是 SARIF**（顶层 `runs[]`），无 `sarif` 包裹字段，默认 Accept 只给 644B 元数据）。且 **SARIF 行号相对该 analysis 的 commit**，跨 commit 比较必须 `git show <sha>:<path>` 回源，不能按工作区行号读（本批加了 docstring ⇒ 位移 +11）。PowerShell 管道会把输出加 BOM 而破坏 `json.load`，取证脚本统一用 `subprocess` 自己取。

## B7b-1 实施：链③ LLM 客户端缓存凭据 slot 化（2026-10-02，含五处自纠）

> 方案：`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md` §4.3 / §6（已拍板三项后开工的第一个 PR，纯 kernel）。只动 `llm/registry.py`，**未碰 `auth.py` 一行**（链①②属 B7b-2/4）。

- **做了什么**：`get_llm_client` 的 `cache_key` 不再放凭据摘要，改放**进程内不透明 slot id**（新 `_slot_for_api_key`，首次遇到某把凭据时按值幂等分配）⇒ 上游 provider 密钥自此不再流入任何摘要函数（切断 `#38` 三条链中的链③）；`_hash_api_key` 连同对 `guardrails.auth.fingerprint` 的 import 一并删除（全仓 `git grep` 实取 `_hash_api_key` 残留 **0** 处）。
- **自纠 1（方案层面的判断错）**：方案 §4.3 原写「代价：缓存键不含摘要 ⇒ 换了密钥会命中同一客户端实例」——**错**，把「键里没有摘要」等同于「键失去密钥区分度」。实际 slot 按凭据值幂等分配，换密钥必得新 slot ⇒ 必不命中旧客户端，区分度**等价保留**；原拟的「守门用例」从「记录退化」变成「证明无退化」（`test_changed_api_key_does_not_hit_old_client`）。**真实代价是另一件事**：明文凭据驻留 `_SLOTS`⇒ 已用 `_MAX_SLOTS = 64` 上界兜住（超限**整表重置并同步清客户端缓存**，否则 slot id 复用会让新密钥撞上旧密钥遗留的实例）；且先实取 `providers.py:82-90` 确认 `ChatOpenAI` 本就长期持有 `api_key` 明文，且正躺在 `_CLIENT_CACHE` 里 ⇒ **不是新增暴露面**。
- **自纠 2（实现层面的无谓绕路）**：先写成 `prov.build(api_key=_slot_value(slot))`，而 `get_llm_client` 手里本来就有明文凭参——绕道 slot 表读回只引入一个**重置窗口竞态**（表刚被清时 `build` 拿到 `None`，使真实 provider 误报「api_key 不能为空」）。已删 `_slot_value`，改回直接用形参（slot 的用途只是缓存键别名，不是凭据的单一来源）。
- **自纠 3（改漏的陈旧描述）**：模块 docstring 仍写 `(provider, model, json_mode, api_key_hash, …)`。修掉的同时把 `api_key_hash` 加进守门禁词，让这个守门用例能拦住「代码改了、文档没改」这一类回归。
- **测试**（数量已实测：文件 `def test_` 计数 5 → 11，即**新增 6 个 + 改写 1 个 + 保留 4 个旧用例**）：新增覆盖 slot 入键不含任何摘要 / 换密钥不命中旧客户端 / 空凭据专用 slot 不占表位 / 达上限重置同时清客户端 / 同名覆盖 provider 失效旧缓存 / **凭据不入日志 sink 的 AST 守门**（见自纠 5）/ **源码级守门：registry 全文不得出现 `hashlib|hmac|fingerprint|sha256|digest|api_key_hash`**；旧用例 `test_api_key_not_stored_plaintext_in_cache_key` 按新契约改写为 `test_cache_key_carries_slot_not_any_digest`（原断言「键内必含指纹」属旧契约实现细节；改写后仍保留且**加严**了「无明文、无指纹、无裸 sha256」三条否定断言，非放宽）。
- **实跑结果**（以修完自纠 5 后的当前树为准，均在本地实跑）：`test_llm_registry_cache.py` **11 passed**；定向集合（`test_llm_registry_cache` + `test_guardrails` + `test_guardrails_fingerprint` + `test_guardrails_fs` + `tests/llm` + `tests/governance/test_thread_identity_migration.py`）**134 passed / 5 skipped（38.0s）**；`ruff check .` exit 0；`scripts/lint_architecture.py` exit 0（P2/P4-2/P5/P6/P7-P11 全过，含 P6 现有白名单未动）。
- **卡点登记（不得规避）**：本地尝试跑 `packages/agent-core/tests` + `tests/governance` + `tests/llm`（collect 实取合计 **557** 用例，其中 agent-core 单目录 **310**）在本机**阻塞**，已用 `-v` 实时重定向定位到具体用例 `packages/agent-core/tests/test_intent.py::test_is_chitchat_false_for_query`（L1 embedder 路径，前 3 个 intent 用例已过）；`git grep` 实取该文件**不引用** `get_llm_client`/`registry`/`api_key` ⇒ 与本批无耦合。**本机不声称全量已验**，全量由 CI 的 `make test`（9 session）兜（PR 检查为权威）。
- **CI 覆盖面实证（上一条卡点的收口）**：核 `Makefile` 发现 9 个 pytest session 中**没有** `packages/agent-core/tests` 独立 session（kernel 靠首条 `uv run pytest -q -m "not requires_pg"` 从**根目录递归**收集覆盖）。本地同命令实取：collect **867** 项，其中 `packages/agent-core/tests` **311** 项（= 存量 310 + 本批新增 AST 守门 1）、`test_intent.py` **13** 项也在内；PR #45 的 CI 实跑该 session **866 passed / 1 skipped / 27 deselected in 61.68s** 全绿 ⇒ 两个结论：① 本批 kernel 改动**确实在 CI 全量覆盖范围内**；② 本机在 `test_is_chitchat_false_for_query` 上的阻塞是**环境局限**（L1 embedder 需外部依赖），非代码缺陷——同一用例集在 CI 61s 内跑完。（备忘：改 agent-core 不会触发名为 agent-core 的 session，定向验证要显式指目录。）
- **自纠 4（数字作用域越界，本条即修正）**：上面那行原先写「agent-core 全量 557 用例」——**557 是三目录 collect 合计，agent-core 单目录实为 310**，把合计数字归给了单一目录。已按 `--collect-only` 实取重述。该错表述同时存在于 commit `fe74e78` 的 message 里；**不回改已推送历史**，以此处为准。
- **自纠 5（本批自引入一条真告警，已真修）**：PR #45 的 CodeQL 报 **`py/clear-text-logging-sensitive-data` high** 于 `registry.py:156`（注解：“`This expression logs sensitive data (password) as clear text`”）——因我为了便于排错把 `slot=%s`（即 `api_key_slot`）加进了 `logger.debug` 实参，而这个值由 `api_key`（password 分类源）数据流而来。**它是本批新引入的，不是存量**。教训：**「不透明」不等于「不可流」——刚把凭据从摘要通路拿掉，就不能反手把它的派生值送到另一个 sink（日志）**，否则只是把凭据从汇 A 搬到汇 B。修法：日志回到只打 `provider/model/json_mode`（旧行为，slot 对排错无价值 ⇒ 删除不损失信息），并新增 AST 守门用例 `test_no_credential_value_reaches_logger_calls`（凭据及其派生名不得作为 `logger.*` 实参）；**已实测该守门对修复前文件报 `(154,'api_key_slot')`、对修复后为空**（否则守门只是装饰）。未使用 dismiss。另已登记为仓级门禁候选（方案 §5，待拍板，本批不擅自扩面）。【补记】本条初稿把规则名写成了截断的 `py/clear-text-logging`，实为 `py/clear-text-logging-sensitive-data`（与仓内 `ARCHITECTURE.md` P7 行及 Batch 6/7 方案一致）——规则名写全才查得到 query，已连代码注释与方案一并订正；也正因为该仓库既有此规则的告警（`#43`/`#44`，均为 fs.py、已 `fixed`），截断名会误导后人去比对不同的规则。本批新告警**只存在于 PR 面**（修前仓库 open 列表仍只有 `#38`/`#39`），修复后 PR 的 CodeQL check 转 pass、新告警计数归 0。
- **验收预期（先说清免得误读）**：B7b-1 单独合入**不会**消 `#38`（还剩链①会话身份与链②限流桶两源）；按方案 §7 判据看「password 分类源数递减」而非闭合，且必须回 `refs/heads/main` 复验（PR 绿 ≠ 主干绿）。
- 附带发现：本仓无 `pytest-timeout`（`uv run --with` 可临时注入），而 Windows 下 `Start-Process -RedirectStandardOutput` + Python 非 tty 会**块缓冲**导致日志 0 字节；可观测的进度定位靠 `-v` 直写文件或前台管道，长用例建议加 `PYTHONUNBUFFERED=1`。

## B7b 强制前置取证完成（2026-10-01，未动任何代码，含一次自我推翻）

> 方案：`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md`（新立）。触发：B7d 收尾时我立的那条强制前置——「拉 `github/codeql` 该查询与其 `SensitiveData` 模型源码，判定源/汇的配置范围，然后才能写 B7b 的验收标准（否则又是一次『看起来能修』）」。

- **取证不靠猜**：`gh api -H "Accept: application/vnd.github.raw"` 直接拉上游 7 个模型文件（`WeakSensitiveDataHashing.ql` / `WeakSensitiveDataHashingQuery.qll` / `…Customizations.qll` / `SensitiveDataSources.qll` / `SensitiveDataHeuristics.qll` / `concepts/CryptoAlgorithms.qll` / `internal/CryptoAlgorithmNames.qll`）。SARIF `codeFlows` 通道仍不可用（`analyses/{id}` 无 `download_url`、`sarifs/{id}` 无 `sip`，令牌缺 `security_events` scope）⇒ 路径结论由「规则源码 + 全仓 grep + 告警列号逐列比对」三者交叉定案。
- **触发条件定案（一条可验证的合取）**：`py/weak-sensitive-data-hashing` 合并两个分支，而 **`"SHA256"` 在 `isStrongHashingAlgorithm` 名单内（`isWeak()=false`）**⇒ sha256 在 `NormalHashFunction` 分支**根本不是汇**（该分支要求 `isWeak()`），只在 `ComputationallyExpensiveHashFunction` 分支成汇，而后者**只接受 `password` 分类的源**。⇒ **`#38`/`#39` 触发当且仅当「一个 `password` 分类的值流入摘要的被摘要位」**（列号已逐列核实：`#38` col 47-69 恰为 `secret.encode(…)` 即 `hmac.new` 消息位，同行的 `pepper.encode(…)` 未被报；`#39` col 29 恰为 `(api_key or "").encode(…)`）。
- **由此推翻我自己几小时前写下的推论（三次自纠）**：新方案初稿 §1 我写「形参 `secret` 自身即源 ⇒ 即使所有调用方都传非敏感值、只要 `fingerprint` 还在摘要就仍报，所以必须删函数才能消 `#38`」——**错**。错因：看到 `SensitiveParameter` 存在就直接推结论，没读完「源分类 ∧ 汇条件」两侧的最终合取（`secret` 分类是 `secret`、不是 `password`，够不到唯一能触发的汇）；更该自查的是**告警文案已经写明 “insecure for password hashing”**，这个在我手上的信息本可直接区分分支。影响：初稿会把方案导向「以删除换绿灯」，实际必要条件是**拆三条链**。教训已入新方案 §1.3：**规则源码取证必须读到两侧合取；告警 message 的措辞是分支指纹，必须优先用来收敛假设**。
- **新锁住一条真通道**：分类**纯由名字决定**（`maybePassword()` 含 `api.?(key|tok)` / `oauth` / `mfa` / `pass(wd|word|code|.?phrase)`，`notSensitiveRegexp()` 也只看名字）⇒「把 `api_key` 改名成中性词」确实能告警消失且属 gaming。因此 B7b 的门禁必须守**语义**（凭据不得进摘要）而非守名字；`scripts/` 也不是逃逸口（仓内无 `.github/codeql/` 配置，Glob 实取 **0** 个 ⇒ default setup 走 autobuild 全仓，脚本仍在分析面）。
- **影响面实取（均为数量/否定式断言，逐条 grep）**：`derive_thread_id` 生产调用点 = **2**（`agent_server/api/auth.py:32` / `agent_federation/api/auth.py:32`，全仓 47 命中其余为测试/脚本/文档）；`server_user_id()` 生产消费者 = **0**（能力存在但从未接线）；联邦 `api/identity_bridge.py:16-18` **显式丢弃 user**；`agent_server/main.py:507` 以 observe 默认挂载（无凭据不绑定）⇒ 新方案写下硬约束：**「有 user 断言」在今天的默认部署里不成立**，必须给主体 id 分阶段来源（否则切 thread_id 直接炸零依赖冒烟）。
- **一个必须写破的现行为**：`resolve_thread_id` 在鉴权启用时忽略客户端 `session_id`、而 `API_KEY` 每部署一把 ⇒ **今天所有持同一密钥的客户端共用同一个 thread_id 会话桶**。任何「按主体细化」都是对外可见的行为变更，不得当作无副作用重构（已列 §8-Q1 待拍板）。
- **另一条机制级修正**：换 scrypt/pbkdf2 **确实能让告警消失**（`SCRYPT` 属 `isStrongPasswordHashingAlgorithm`，两分支汇条件都不再命中），所以它不是「看不见」而是「按规则字面要求办」；仍不选的理由降为纯工程判断（本仓输入是高熵随机密钥、产物只做查表标识、在中间件热路径每请求算一次，慢哈希前提不成立且使既有会话全漂移）——把「能不能消」与「该不该消」分开记账，以免后续争论失去事实底座。
- **账面同步三处**：新方案入库；Batch 7 方案新增 **§4.2**（宣布强制前置已完成 + 订正 §4.1 的过头推论，并保留原文不改写）；`docs/TODO.md` §8 将「B7b 可直接落在已断言主体上」这句乐观说法订正为两处硬约束 + 接上新方案。**未动 `auth.py` 一行代码**（先方案后编码）。
- **工具链异常登记**：本次新方案首次落盘时出现部分中文 mojibake（全角标点处被误作 GBK 重编码），已整份重写，并用 `git grep -I -e 锛 -e 锟 -e 鎴` 全仓扫描确认现存跟踪文件 **0 命中**。以后写中文长文档后必须回读一次校验编码。

## B7d：合流后主干复验发现新告警 #48，按三层齐备真修（2026-10-01，PR #42 已合入 `9ee0000`，主干复验通过）

> 方案：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §7。触发：v3 合流（PR #41）合入后回主干复验，硬指标未达成——open 不是 2 而是 3。

- **事实**：新增 **#48 `actions/missing-workflow-permissions`** @ `.github/workflows/ha-assembly.yml:30-56`，`created_at=2026-10-01T12:55:08Z`（PR CI 期间）、`updated_at=13:01:20Z`（主干重扫复现）。引入源：`70f2b83` 经 merge 第二父进来，即 **v3 侧提交新增该 workflow**（`git diff --name-status b67546d 889d417 -- .github/workflows/` = `A`）。#38/#39 无位移（仍 `auth.py:92` col=47 / `:117`）。
- **不采的捷径**：只给被点名的 job 补一行权限（散点式）；dismiss；在 default setup 里按路径排除 `actions/*` 查询；把权限写成 `write-all` 求个「不报」。
- **单一实现（对齐既有约定，不新发明）**：审计 4 个根 workflow，`agent-platform-ci.yml`/`eval-llm.yml`/`ha.yml` 均已有顶层 `permissions: contents: read`，**`ha-assembly.yml` 是唯一漏接者**（顶层与 job 级均无）。已按同形状补齐；`contents: read` 是它实际所需最小面（只用 `actions/checkout` + `docker compose` + `curl`，不上传 artifact、不写仓库）。
- **强制门禁（新增 P11）**：`scripts/lint_architecture.py` 扫根 `.github/workflows/*.yml|yaml`，**缺顶层 `permissions:` 块**、取值为 **`write-all`**、或为空块即 exit 1；自研 fail-closed（workflow 目录不存在也不得静默放行）。只认顶层块的理由：顶层声明由构造保证覆盖全部 job，job 级声明易漏。
- **治理用例**：`tests/governance/test_workflow_permissions_governance.py` 17 条——正反例（缺块/仅 job 级/`write-all`/空块/注释伪装）、当前树零违规、临时根探针验扫描面、目录缺失 fail-closed，及一条**回归锁**：把任一真实 workflow 的顶层 `permissions` 块剥掉必须立刻判违规（排除「门禁只是恰好没命中」的假通过）。
- **登记位**：`ARCHITECTURE.md` 新增 **§4.1 强制门禁登记表**（P2/P4-2/P5/P6+P6-2/P7/P8/P9/P10/P11 × 锁住的告警形状 × 治理用例）。这是补合流方案 §8-3 的欠账——当时承诺「在 `ARCHITECTURE.md` 登记」但只落在 CHANGELOG，P9/P10 一直无登记位。
- **本地验证**：`lint_architecture` exit 0（9 组：P4-2/P2/P5/P6+P6-2/P7/P8/P9/P10/P11）· 新用例 17 passed · `tests/governance` 全 session **242 passed** · `ruff check` 无告警。门禁有效性反喂取证：将 `git show HEAD:` 的**修复前原文**送进 P11 → 判「缺顶层 permissions 块」，修复后同一函数 → `None`。
- **账面自纠（顺带查到，与本告警无因果）**：`plan-v3-identity-merge` §9.2 与 PR #41 描述均写着「仓内无 `uv lock --check` 门禁」——**错**：`make ci` 末行就是 `uv lock --check`（Makefile:71），而 CI 直接复用 `make ci`（`agent-platform-ci.yml:65`）。「不破 CI」的结论仍成立，但依据换成实证：本机 `uv lock --check` exit 0，且 PR #41 的 `ci` ×2 job（含 `--check`）已 pass。残留风险已登记：CI 的 uv 版本由 `setup-uv@v7` 决定且不钉，将来两端 marker 规范化不一致时 `--check` 可报「lock 已过期」而红；根治是在 workflow 钉 uv 版本（独立决策，未在本批做）。教训：**否定式断言（“仓内无 X”）必须 grep 过才能写**。
- **主干重扫验收通过（本批的终态判定）**：PR #42 自身 5 项 checks 全 pass（`Analyze (actions)`/`Analyze (python)`/`CodeQL`/`ci` ×2），merge commit `9ee0000`@13:41:19Z。合入后在 `refs/heads/main` 实跑复验（`.codeartsdoer/temp/verify_main_b7d.py --once`）：**open 2 / fixed 44 / dismissed 0**；**#48 `state=fixed`、`fixed_at=2026-10-01T13:42:00Z`、`dismissed_at`/`dismissed_by`/`dismissal_reasons` 全为 `None`**（合入后 41 秒自动闭合，非人工 dismiss）；全仓最大告警号仍为 **48**，合入时刻之后**新建告警 0**；`#38`/`#39` 位置不变（`auth.py:92` col=47 / `:117` col=29），**无位移重开**。主干 push 的 check-runs：`Analyze (actions)` success@13:42:11Z、`Analyze (python)` success@13:42:59Z、`ci`（含 P11 lint + 17 条治理用例）**success@13:46:20Z** ⇒ P11 是**在主干真实跑过**，不只是本地跑过。
- **判据脚本自身的一次纠错**：v3 版复验脚本第 [G] 项靠 `check-suites` 的套件名关键词过滤 CodeQL，实测该接口 `name` 字段为 **null** ⇒ 判据永远落在「尚未 completed」，属于「查不到就当没完成」的假保守；同时 `most_recent_instance.location` 是 `{path, start_line, start_column}` 而**非** SARIF 的 `physicalLocation`，误按后者解析会得到 `?:?`。本版改为直读 `check-runs` 的 `Analyze (python)`/`Analyze (actions)`/`ci`，并把「**未见主干 push 触发的 ci run**」也判为验收未达成（fail-closed），避免把取证工具的盲区当成通过信号。
- **B7b 账面两处订正（收尾时 grep 实取，未改任何代码）**：① 方案 §4 原写 principal_id 化后「#38 与 #39 同时**真消失**」——**错**：`#38` 落点在共享实现 `fingerprint()` 内部（`auth.py:92`），除会话派生外还喂着 `resolve_client_key` 限流桶与 **`llm/registry.py:46`**（LLM 客户端缓存键，且它是**上游 provider 密钥而非调用方身份**，拿 principal_id 替代不成立）两个输入源；`#39` 落在 `legacy_thread_id`（为算 legacy→new 映射而故意保留，P6-2 锁调用面）。⇒ 已新增方案 **§4.1** 写清三个输入源与「规则是过程内还是全局流」这个待验证前置（沿用 Batch 7c「先实测再动手」）。② 旧 Batch 2 方案 `plan-codeql-codescanning-remediation` 至今仍列着两条可执行的 dismiss 文案/命令（#38 `false_positive` / #39 `wont_fix`）——已加 **作废横幅**：实测主干 `state=dismissed` 计数为 0，它们从未执行也不得再执行（破窗风险：历史文档里存着看似仍有效的 dismiss 步骤）。订正过程中我自己又写了一句未经 grep 的引用（「TODO 原写两调用点」，实际全仓 md 无此句），已当场删除并登记为二次自纠。

## v3 身份层合流 main（B7b principal_id 化的前置）（2026-10-01，PR #41 已合入 `a660e76`）

> 方案：`docs/plans/plan-v3-identity-merge-2026-10-01.md`（§9 为执行记录）。触发：用户在 B7b 落地上拍板「先合流 v3 身份层，再做 principal_id 化」——`#38`/`#39` 的病根（单一静态 `API_KEY`、无 key→主体映射）与 v3 上已 Accepted 的 ADR-0007 同一条；直接在 main 再造 principal 注册表就会形成**第三套身份机制**，违反「横切关注点单一实现」。

- **合流粒度**：`git merge origin/v3` 一次全量（v3 ahead 47 / main ahead 49，merge-base `2a5e633`），**不 cherry-pick、不用 `-X ours/theirs` 压冲突**；47 个 commit 的作者与关联完整保留。
- **带入的内容**（main 此前全无）：`agent_runtime/identity.py`（RS256 签/验 + 网关→子服务 HMAC 内部头 + JWKS 轮转 + 启动守卫）、`identity_middleware.py`（纯 ASGI）、联邦 `api/identity_bridge.py`（`X-Tenant-JWT`）、ks `utils/tenant_identity.py`、内核 `memory/_tenant_gate.py`、ADR-0006/0007、migration `006`–`010`、5 条 governance 红线测试与 HA 租户隔离用例。
- **五处冲突的处置**：`lint_architecture.py` 两侧门禁**全保留**，v3 两条续编为 **P9（禁散点 tool 埋点）/ P10（禁 `from tools.*` 直引绕过 `get_tool()`）**；`agent-runtime/pyproject.toml` 取并集（新 `identity = ["PyJWT[crypto]>=2.9"]` extra）；`CHANGELOG.md` 两条时间线分段并存（append-only，不改写不重排）；`dep-security-accepted-risks` add/add **以 main 为基底**（它是含 09-30 证伪的演进后超集）并并回 v3 独有的一条 `uv tree -i` 排查手法；`uv.lock` 经 `uv lock` 重生成（未手改）。
- **合流新暴露并已真修的第 6 处（非 dismiss、非放宽门禁）**：`check_doc_sync.py` 报 `ARCHITECTURE.md` 两条**悬空引用**（`docs/adr/0005`、`docs/plans/plan-memory-hardening-2026-09-27.md`）——两文件在 `main`/`v3` 均不存在（v3 自身早就不一致），只存在于 `feat/isolation-hardening`@`d4b6faa`。导入其**「提案」版**并逐文件加来源标注：该分支后续 `ff68aee` 声称「T0 已落地」，但主干 `git grep -l -e EpisodicStoreProtocol -e supports_episodic` **0 命中**、`agent_core/memory/` 无 `execution.py`，故**不采信该修订**；真正随合流落地的是 T1（`010_episodic_tenant` + HA 用例）。
- **运行侧（已在 `.env.example` 登记 12 项）**：`DEPLOY_ENFORCE_IDENTITY` **默认 false** ⇒ 零依赖冒烟不受影响（实测：默认档 `agent_server.main:app` 构造成功、中间件栈含 `IdentityMiddleware`；置 true 且无公钥无 `SINGLE_TENANT` → `RuntimeError` 拒启动，开关不是摆设）；本次**不**把默认值改成 fail-closed（独立决策）。
- **新登记技术债（`ARCHITECTURE.md` §2.3/§5）**：`IdentityMiddleware` 仅覆盖 2/6 应用（agent_server + federation 无条件挂载；ks 走自有 `TenantHeaderMiddleware`；exhibition/kefu/nl2sql 入口 grep **0 命中**）——`TENANT_JWT_ENFORCE` 硬切换前必须先补齐装配层 + 新增 lint 不变量，不得靠「每个 app 记得调一次」。
- **本地验证（全绿）**：`ruff` 无告警 · `lint_architecture` exit 0（P4-2/P2/P5/P6+P6-2/P7/P8/P9/P10 全在位）· `check_doc_sync` exit 0 · 9 个 pytest session：根 839 passed/5 skipped、agent-runtime 606（含 27 条 identity）、governance 225、agent-core 300/5、agent_server 44、联邦 163、ks 238/13、shared-schemas 28、kefu 43、exhibition 347/1、nl2sql 18；`tests/ha` 1 passed/26 skipped（本机无 PG，skip 属设计意图，真 PG 结果交 CI）。`uv lock` 除 identity 条目外还归一化了约 30 行 environment marker（本机 uv 0.11.21 与 lock 原生成版差异，无包名/版本变动，已实查确认 CI 不走 `--frozen`）。
- **验收硬指标（实跑结果：未达成，已转入 B7d 真修）**：PR #41 自身 checks **全 pass**（`Analyze (actions)`/`Analyze (python)`/`CodeQL`/`assembly` ×2/`ci` ×2/`ha` ×2），其中 `ha` job 在真实 PostgreSQL 16.15 上 **27 passed in 8.07s**（覆盖本机 26 条 skip，kill -9 双进程接管真跑）——此前唯一未知项已坐实。但合入（13:00:43Z）后主干 `refs/heads/main` 复验为 **open 3 / fixed 43 / dismissed 0**：多出的 **#48 由 v3 侧新增的 workflow 带入**，即「合流未新增任何告警」不成立 → 按本批约束真修，见顶部 **B7d** 节。

## Batch 7c：#47 按官方编码形状重写 `resolve_within`（2026-10-01，分支 `fix/codeql-batch7c-path-shape`，PR #39 已合入 `bb46dd3`）

> 接 Batch 7a：主干重扫发现 #42 只是**位移重开**为 #47（同一语句）。方案：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §3.4。

- **机制取证（先实测再动手：不凭记忆，直接拉 `github/codeql` 源码）**：`py/path-injection` 是**带状态**污点追踪（`NotNormalized` → `NormalizedUnchecked`），查询注释原话 “Such checks are ineffective in the `NotNormalized` state”。被识别的规范化**只有** `os.path.normpath`/`abspath`/`realpath`；被识别的 safe-access 守卫**只有** `str.startswith`；而 `Path.resolve()` 不是规范化、它是 `FileSystemAccess` 的 sink。⇒ Batch 6 的「结构不可消除」与 Batch 7a 的「已推翻 Batch 6」两头都错：真因是我们从未走官方编码的 **规范化→前缀守卫→才接触文件系统** 形状，`is_relative_to` 检测器根本不认。
- **修法**：`resolve_within` 改为 `os.path.normpath(os.path.join(root, raw))` 词法定形 → `startswith(root_str)` 且带**分隔符边界**（补上 naive startswith 会误放行 `/data/root_evil` 的真漏洞）→ 才 `Path(norm).resolve()` → 保留解析后复检（挡软链逃逸）。POSIX 反斜杠二次解释改为**纯词法**否决，不再第二次触碰文件系统（顺带消掉同源的潜在 sink）。
- **接受集不变是差分实测出来的，不是推演**：本机用 `posixpath` + `PurePosixPath` 模拟 POSIX 宿主，42 个入参对跑旧/新裁决 → **差异 0**。它当场推翻了我自己先写下的「lone `\` 入参改为拒绝」断言（`posixpath.join` 会自动插入分隔符，两版均放行），该用例已改正并入库。唯一真收紧在 **Windows 宿主的大小写变体绝对入参**（旧：`is_relative_to` 走 `normcase` 不区分大小写→放行；新：`startswith` 区分→拒绝），方向为变严，已用 `skipif(!win32)` 用例固定。
- 新增 6 条回归（base 自身放行/兄弟前缀被拒/`..` 定形后不进 `resolve`/反斜杠否决不新增 `resolve` 调用/lone-`\` 仍放行/Windows 大小写变体拒绝）；本目录 49 passed / 5 skipped（Windows 宿主）。
- **主干重扫验收通过（本批的终态判定）**：PR #39 全 checks pass（含 `CodeQL`，推送前另跑 L3 深度审查 findings 0），合入 `bb46dd3`@11:42:39Z；`refs/heads/main` 的 default-setup 分析（`Analyze (python)` success）于 11:44:14Z 将 **#47 置为 `state=fixed` 且 `dismissed_at=None`（自动闭合）**，且全仓告警最大号仍为 #47、合入后**无任何新建告警** —— 即 **#47 真消失，不是再一次位移重开**。`refs/heads/main` 总账：45 条 CodeQL 告警，`fixed` 43 / `open` 2，**open 仅剩 #38 / #39**（待 B7b principal_id 化）；43/43 闭合全为自动，**全仓零人工 dismiss**。

## Batch 7a：取消 dismiss 通道，剩余告警真修（2026-10-01，分支 `fix/codeql-batch7-real-fixes`，PR #38）

> 触发：用户明确「不要用 dismiss 这种简单的处理方式」。方案：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md`。

- **`#34`（`gateway/gray.py` 灰度分桶）MD5 → SHA-256**：官方 query help 对非口令场景的直接建议即 SHA-2，且 `user_id` 属可识别信息。影响面实测：`GRAY_PCT` 默认 `0`、`is_in_gray` 在产品代码里**无调用点**、分桶不持久化 → 人群重排无生产影响。
- **`#43`/`#44`（`guardrails/fs.py` 拒绝日志）契约变更：不落任何路径文本**，只留原因 + 数值型结构摘要（`len`/`fragments`/`absolute`）。**演进过程值得记**：首版只去掉 `base`/`resolved`、保留 `input=%r`，PR #38 的 `CodeQL` 检查仍报 2 new alerts（high，注解 `fs.py:99`/`:110`）⇒ 消除法证明被判 secret 的是**入参本身**（路径含凭证派生的 `session_user-<HMAC(api_key)>` 目录名）——**这不是误报**。官方口径仅“Sensitive data should not be logged”，无 masking/哈希豁免。Batch 3 定的「留痕含原文」因此作废，排障改走接入层访问日志或本地复跑；`api/server.py` 依赖旧语义的注释同步修正。
- **`#42`（`resolve_within`）在 `resolve()` 之前加纯词法 containment 守卫**：不再对未验证的越界输入做文件系统解析，且不放宽接受集（`a/../b` 词法判真，符号链接逃逸仍由解析后复检拒掉）。**主干重扫实测：本动作未消除告警** —— #42 旧号 `state=fixed`，但同一语句（`resolved = candidate.resolve()`）在位移后的 `fs.py:187` 重开为 **#47**；因此当时写的「以代码重构推翻 Batch 6『结构不可消除』」**证据不成立，已撤回**（守卫前置作为纵深改进保留，真修见顶部 Batch 7c）。
- **新增 4 条回归**：日志不含部署绝对路径×2、越界输入不进 `resolve`、软链逃逸仍拒（其中两条断言方向随契约修正，新断言比旧的多两项，非收窄凑绿）。
- **本地验证**：`lint_architecture.py` exit 0、`check_doc_sync.py` 0 警告；分 session agent-core 281 passed/3 skipped、根 `tests` 500 passed/17 skipped、联邦 152 passed；`ruff` 无告警。本机无 CodeQL CLI，告警闭合以 PR 检查与主干重扫为准。
- **不以 dismiss 收尾**：`#38`/`#39` 属「把 API Key 摘要成用户标识」的模式问题（取证：`verify_api_key` 走 `secrets.compare_digest` 明文比较，派生值从不参与验证，所以「用于口令哈希」的判定不成立；但「会话标识可由凭证推导」的耦合是真的），需 principal_id 化的架构决策，本批不动代码，三条出路已列在方案 §4 待拍板。

## Batch 6 验收：模型包生效，主干 open 9 → 6（2026-10-01，分支 `docs/codeql-batch6-acceptance`）

> 纯文档（不改产品代码）。PR #36 合入 `main` = `0bc5175` @09:19:03Z，默认分支重扫 09:20:29Z（CodeQL 2.27.1）。

- **闭合 3 条，均为 `state=fixed` 且 `dismissed_at=None`（自动闭合，非人工）**：`#23`（`agent_federation/api/server.py:264` `FileResponse(abs_path)`，barrier 生效）、`#40`（`fs.py:119`）、`#41`（`fs.py:134`）（后两条靠 `barrierGuardModel`）。`#23` 闭合同时反证仓内模型包**确实被 default setup 自动加载**（上一节据此推翻的选型前提得到实测支持）。
- **`#42` 仍 open，且经分析为结构不可消除**：`resolve_within` 必然是 `candidate.resolve()`（`:162`）→ `_ensure_within`（`:167`），**不先 resolve 就无从判断越界**，sink 永远在守卫之前，所以 guard 建模无法覆盖。唯一能“消掉”它的做法是把 `Path.resolve` 返回值全局声明为 barrier，而 `resolve()` 本身不做任何净化、且会屏蔽全仓其他真实路径注入——**否决，转人工 dismiss**。这条边界写进方案 §9.1。**（订正：该判定已于 Batch 7c 推翻——真正的原因是 `Path.resolve()` 不被识别为规范化，必须先 `os.path.normpath` 再用 `str.startswith` 守卫；#42 后来位移重开为 #47 并在 7c 真修。）
- **本会话累计账面**：`refs/heads/main` open 21 → 6。剩下 6 条全部是「代码无需修、只需面板 dismiss 附证据」：`#34`（灰度分桶真误报）、`#38`/`#39`（HMAC/sha256 形状属实不可消除）、`#43`/`#44`（不在可建模 sink kind 清单）、`#42`（上述结构边界）。**即已不存在应当改产品代码而未改的 CodeQL 告警。**
- **仍未做的验收项**：模型包非空转自证（删 barrier 行→重扫必复报 `#23`）。现有旁证（加包前 open / 加包后 fixed，代码未动）不等于反证已做，已记在方案 §6-2。

## Batch 6 执行：仓内 CodeQL 模型包把 kernel guardrails 声明为 path-injection barrier（2026-10-01，分支 `fix/codeql-batch6-model-pack`）

> 零产品代码变更，仅新增 2 个 YAML。**同时推翻本文件下一节的一个选型前提**（已就地标记）。

- **产物**：`.github/codeql/extensions/agent-platform-python/codeql-pack.yml`（`library: true` + 无 dependencies + `extensionTargets: codeql/python-all: "*"` + `dataExtensions`）与 `models/agent_core.guardrails.fs.model.yml`：`barrierModel` 将 `safe_filename`/`safe_join`/`resolve_within` 的返回值声明为 `path-injection` barrier（每个 helper 写两种 `type` 形态匹配不同导入形式），`barrierGuardModel` 将 `Path.is_relative_to`（接收者用 `Argument[this]`）声明为守卫。
- **选型前提纠正**：原计划「必须停用 default setup 并切 advanced setup」错误——官方文档明说仓级模型包放 `.github/codeql/extensions/` **会被自动检测并使用**，两种配置模式均识别。“已发布”限制只适用组织级扩展。结果：**零基础设施变更、零扫描黑窗、不多花 Actions 分钟**，避免了一次多余且有风险的面板切换。
- **写法修正**：原方案写的「声明为 `sanitizer`」与「`PathTraversalError` 声明为 taint-blocking 异常」在 Python 数据扩展中**没有对应谓词**（官方只有 `sourceModel`/`sinkModel`/`summaryModel`/`barrierModel`/`barrierGuardModel`/`typeModel`），改为 barrier + guard 两种可表达的形式。
- **边界说明**：`py/clear-text-logging-sensitive-data`（`#43`/`#44`）**不在可自定义的 sink kind 清单内**（官方列 9 种），因此无 barrier 可写，只能人工 dismiss——原「两个终态二选一」由此变成技术上的单选项。
- **验收分层**：本机已验——两个 YAML `safe_load` 通过、列数与官方谓词签名一致、pack 无依赖、`check_doc_sync.py` 0 警告、`lint_architecture.py` exit 0（P7 未放宽）；**未验**——包是否真被加载、`#23`/`#40`~`#42` 是否闭合（本机无 CodeQL CLI，以 PR 的 CodeQL 作业不报红 + 合入后主干重扫差集为准）。

## CodeQL 合入后默认分支重扫对账：19/21 闭合，另暴露 5 条 kernel 模型缺失告警（2026-10-01，分支 `docs/codeql-post-merge-rescan`）

> 本分支**纯文档**（不改产品代码）。触发：PR #33（`8b6d416`）与 PR #34（`4f8ae4c`）合入 `main` 后自动重扫的结果核对。

- **闭合情况**：`refs/heads/main` open 21 → 9，其中原 21 条有 **19 条 `state=fixed`**（无 dismiss）——C 类 `py/stack-trace-exposure` ×4、D 类 `actions/missing-workflow-permissions` ×3、E 类 `py/incomplete-url-substring-sanitization` ×1 全清，A 类 8 条中 7 条清，B 类 4 个 api-key 站点全清。PR #34 自身 `CodeQL` 检查 pass（doc-sync 改动零告警）。
- **新暴露 5 条（本条重点）**：`#40`/`#41`/`#42` `py/path-injection` 落在新建 kernel `agent_core/guardrails/fs.py` 内部的 `Path(...).resolve()` 调用点（`:119`/`:134`/`:162`），`#43`/`#44` 为新规则类 `py/clear-text-logging-sensitive-data`（同文件 `:93`/`:103` 两处拒绝日志回带入参原文）；另 `#23`（`FileResponse(abs_path)`）未闭合。**根因同一**：CodeQL 内建模型不认识 `safe_join`/`resolve_within`/`safe_filename` 为 sanitizer，所以污点既能追到调用点 sink，也能追进 sanitizer 内部把其 `resolve()` 当 sink 报。
- **推理越界的纠正**：上游方案曾以「PR 重扫无新增 A/C/E/D 告警」作为反向证据，判定「无需为此补 data-extension」——**不成立**。`refs/pull/33/head` 与 `refs/heads/main` 是两套告警集合，跨过程的 kernel 内部 sink 只在默认分支模式下暴露。教训：**证据的作用域不能超出产生它的分析模式**；所以下结论必须回到最终作用域（默认分支）复验。已在原文处加纠正标记。
- **预测命中**：`#38`/`#39`（kernel `guardrails/auth.py:92`/`:117`）如预期从 PR 作用域迁入 `refs/heads/main` 并重新开号——印证 dismiss 是按 ref 生效、不能只在 PR 上做一次。
- **后续方案（已执行，见上一节）**：`docs/plans/plan-codeql-batch6-kernel-sanitizer-models-2026-10-01.md`。选型实查：本仓为 PUBLIC；CodeQL 跑的是 default setup（仓内无 codeql workflow/config），而 ~~default setup 只接受**已发布**的模型包——所以仓内本地 `.model.yml` 必须配 advanced setup 才生效~~ **【此句已于执行时被推翻：仓级包放 `.github/codeql/extensions/` 即自动加载，该限制只适用组织级扩展，见上一节】**。“已切 advanced setup + 仓内模型包”的推荐收敛为“只加仓内模型包”；已否决的「在调用点内联 `is_relative_to` 复检」（与 P7-1 不变量正面冲突且消不掉 kernel 内部告警）维持否决。
- **仍待人工**：`#34`（`gateway/gray.py:40` 灰度分桶，真误报）与 `#38`/`#39` 的 dismiss 需 `security_events` scope（实测本机令牌仍不含）；部署需配 `AGENT_PLATFORM_SECURITY_PEPPER` 并先 dry-run `scripts/migrate_thread_identity.py`。

## doc-sync 门禁补齐「文件引用」校验 + 修复存量路径漂移（2026-10-01，分支 `fix/doc-sync-file-ref-gate`）

> 方案：`docs/plans/plan-doc-sync-file-ref-gate-2026-10-01.md`。背景：PR #33（CodeQL 收敛）收尾排查时发现 `ARCHITECTURE.md` 一条文件引用指向不存在的路径而 CI 全绿；与 CodeQL 主题无关，故拆独立分支。

- **① 存量漂移修复**：`ARCHITECTURE.md` 「历史命名残留」条目中 `docs/architecture-boundary-app-vs-agent-federation.md` → `docs/architecture/architecture-boundary-app-vs-agent-federation.md`（原路径不存在；`origin/main` 同样如此）。
- **② 强制门禁**：`scripts/check_doc_sync.py` 的 `check_architecture_paths()` 原先只对以 `/` 结尾的**目录**引用调存在性校验，带扩展名的文件引用直接落空；`check_agents_md_paths()` 只匹配表格首列。现新增 `is_doc_file_ref()` 谓词 + `check_doc_file_refs()`（由 `main()` 统一装配），对 `AGENTS.md` / `ARCHITECTURE.md` / `README.md` 三份现状文档逐行取反引号片段，命中「顶层前缀 + 已知扩展名 + 无通配/占位/空格」即复用既有 `check_path_exists()` 报错。判定面刻意保守：宁漏报不误报（误报会把门禁变成噪音并诱导关掉它）。
- **CHANGELOG 故意不校**：一次性探测 4 份顶层文档得 117 个文件引用、25 个不存在，其中 24 个在 `CHANGELOG.md`（历史条目所指文件后来被移动/重命名）。append-only 历史快照按既有约定不回改，纳入校验即上线一片红；故范围排除，并在单测里钉住该排除（防后人“顺手”加回来）。
- **防静默失效**：新增 `tests/governance/test_doc_sync_file_refs.py`（17 例）——真实树 0 违规 + 人为插入不存在的引用必报错（非空洞性）+ 通配/占位/模块路径/外链/目录引用不误报 + CHANGELOG 排除断言。门禁谓词若被改坏，检测面会归零而 CI 仍绿，本套用例即拦这一手。
- **实测证据**：修前 `uv run python scripts/check_doc_sync.py` 退出码 1 且恰好报出上述 1 处（零误报）；修后退出码 0、0 警告。`uv run pytest tests/governance -q` 115 passed · `ruff check` 通过 · `scripts/lint_architecture.py` 全项通过。
- **附带纠正（不属本分支代码改动）**：曾误登记「根 `AGENTS.md` 引用了不存在的 `docs/operations/testing-playbook.md`」——实测该引用只在 `feat/isolation-hardening` 的 AGENTS.md（该分支持有该文件），主干命中 0，属把会话上下文缓存的另一分支文件当成本分支事实。纠正记录在 PR #33 分支 `4acd366`。

## CodeQL 告警收口 Batch 1~5：workflow 最小权限 + 密钥指纹 DUP-1 + 路径注入 + 堆栈回显 三层收敛（2026-10-01）

> 方案：`docs/plans/plan-codeql-codescanning-remediation-2026-10-01.md`（已批准）；散点根因复盘：`docs/plans/plan-duplicate-logic-inventory-2026-10-01.md`。
> 背景：Code Scanning 21 条 open（14 high / 7 medium），其中 `py/weak-sensitive-data-hashing` 的根不是“哈希选错”而是“同一 `sha256(api_key)` 派生被抄 4 遍且截断语义分裂”。

- **Batch 1（D 类、3 medium）**：`.github/workflows/{agent-platform-ci,eval-llm,ha}.yml` 加顶层 `permissions: contents: read`（三个 workflow 全程只读仓库；`upload-artifact` 走独立 artifacts 服务不需额外 scope），收口 `actions/missing-workflow-permissions`。
- **Batch 2 ① 单一实现（kernel）**：`agent_core.guardrails.auth` 新增 `fingerprint(secret, *, length=None)` = `HMAC-SHA256(AGENT_PLATFORM_SECURITY_PEPPER, secret)`，截断有 **32 hex（128bit）下限**（低于即 `ValueError`，使 48bit 弱身份在本 API 上不可能再被写出）；`derive_thread_id(api_key)` 统一会话身份格式（`user-` + 32 hex）；`legacy_thread_id` 仅作迁移映射用（保留旧格式可复算）。未配 pepper 仍可运行，启动告警一次。
- **Batch 2 ② 站点收敛（消除 4× 重复，含 DUP-3）**：`guardrails/auth.resolve_client_key`（限流桶）、`llm/registry._hash_api_key`（LLM 客户端缓存键）、`agent_server/api/auth.resolve_thread_id`、`agent_federation/api/auth.resolve_thread_id` 均改指 kernel 实现；两个 app 的 `dev-default-thread` 字面量上收为 kernel `DEV_THREAD_ID`。`gateway/gray.py` 的 `md5(user_id)` 灰度分桶经实读定性为 **唯一真误报**（非密钥、非隔离），**不改码**，走 GitHub dismiss 附证据。
- **Batch 2 ③ 强制门禁（P6，三层补齐）**：`scripts/lint_architecture.py` 新增不变量——同一行出现弱哈希调用 + `api_key/secret/password/access_key/private_key` 语义标识即失败（全仓扫描，白名单仅 kernel 单一实现文件）；`hmac.new(secret, msg, hashlib.sha256)` 不命中（无紧跟 `(`）而 HMAC 恰是鼓励写法；`md5(user_id)` 不含密钥语义名，无需为其开白名单。自测：临时埋入违规探针 → 退码 1（并由 `tests/governance/test_thread_identity_migration.py` 以临时根目录固定此行为）。
- **派生变更的兼容路径（实施风险项）**：会话身份值改变会使旧 `updated/session_user-<legacy>/` 目录与 checkpointer `thread_id` 行对不上。新增 `scripts/migrate_thread_identity.py`：默认 dry-run，`--apply` 才改名，碰撞拒绝覆盖并计入 skipped；DB 部分**只打印 SQL 不代执行**（本仓 CI 无 PG，拒绝把未实跑验证的破坏性写操作固化进脚本，已在脚本 docstring 定为边界）。
- **登记**：新 env `AGENT_PLATFORM_SECURITY_PEPPER` 入 `.env.example` 与 `packages/agent-core/README.md` 环境变量清单；根 `tests/conftest.py` 将该变量加入 `_CLEARED_VARS`（否则本机 shell 设过 pepper 时指纹与测试期望不一致）。
- **测试**：新增 `packages/agent-core/tests/test_guardrails_fingerprint.py`（稳定性/区分度/pepper 依赖/长度下限/HMAC 等价/限流桶走同一实现）与 `tests/governance/test_thread_identity_migration.py`（P6 反例与正例 + 全仓零违规 + 迁移改名/碰撞/dry-run）；`tests/governance/test_auth.py` 与 `applications/agent_federation/tests/test_auth.py` 按新契约改写（断言与 kernel 单一实现一致 **且** 不再等于旧 `sha256(...)[:12]`，摘要宽度 12→32），断言未收窄。
- **Batch 3 ① 单一实现（kernel）**：新增 `agent_core.guardrails.fs`：`safe_join(base, *parts)`（拼接语义：绝对片段 / `..` / NUL / 空片段一律拒绝，拼接后仍做 resolve 包含判定，故也挡符号链接逃逸）、`resolve_within(base, user_path)`（解析语义：兼容 `/api/files` 把绝对路径原样传回的现有契约，但结果必须位于 base 内）、`safe_filename(name)`（basename + 字符白名单，`.`/`..`/空归 `_`）；`PathTraversalError` 继承 `ValueError`（宿主旧 `except ValueError` 仍兜得住），且**异常消息不带入参原文**（越界线索只进服务端日志），避免被 `detail=str(e)` 类写法带进出站响应。
- **Batch 3 ② 站点收敛**：`agent_federation/api/server.py` 三个文件端点（`/api/upload`、`/api/download`、`/api/files`）删除本地 `_sanitize_filename` 与两处手写 `resolve() + is_relative_to`，全部改调 kernel helper；同时把 `:284` `detail=f"路径无效: {e}"`、`:300` `detail=str(e)` 改为固定文案 + `logger.exception`（C 类堆栈回显的同源站点顺带消除）；`/api/download` 存在性判定由 `exists()` 收紧为 `is_file()`（不再把目录当文件回传）。
- **Batch 3 ③ 强制门禁（P7，三层补齐）**：`scripts/lint_architecture.py` 新增 P7-1（白名单外禁手写 `.is_relative_to(`，包含判定只允许 kernel 一处）+ P7-2（`applications/**` 下路径含 `/api/` 的模块，若有 `FileResponse(` / `.rglob(` / `.glob(` 出口却未调 `safe_join`/`resolve_within` 即失败）；白名单：kernel `guardrails/fs.py` 与 ks 两个静态页面 router（路径来自 `PROJECT_ROOT` 常量、无请求输入，已注理由）。
- **对外契约审计（不为统一而静默破坏兼容）**：`path` 入参在本仓 grep 仅命中定义处（无仓内消费者），前端为外部消费者且习惯把列表返回的**绝对路径原样回传**，故 `resolve_within` 保留对绝对入口的宽容（只要求落在 base 内），未收紧为“仅相对”；越界仍 403、缺失仍 404，仅“畸形入参（空/NUL）”由 400 归入 403。
- **Batch 3 测试**：新增 `packages/agent-core/tests/test_guardrails_fs.py`（拼接/解析/净化三入口的正反例 + 异常消息不泄漏 + 符号链接逃逸，Windows 无特权建软链故 2 例 skip）、`tests/governance/test_path_io_governance.py`（P7 反例/正例 + 当前树零违规 + 临时根埋探针验判定面）与 `applications/agent_federation/tests/test_file_endpoints.py`（直接调用 handler 断言 403/404/固定文案/上传落点净化）。
- **Batch 3 跨平台补修（CI 的 Linux runner 拉出的真缺陷）**：上述单测在 Windows 本地全绿，但 PR #33 的 CI 失败 4 条——`safe_join` 对 `C:\Windows\win.ini` / `\\server\share\x` DID NOT RAISE、`resolve_within` 对 `C:\Windows\win.ini` DID NOT RAISE、`safe_filename("..\\..\\windows\\win.ini")` 未去目录。根因是实现直接依赖 `pathlib` 的**宿主语义**（`Path.is_absolute()` / `Path.parts` / `Path().name` 在 POSIX 下均不将 `\` 视为分隔符），而服务入参可能来自 Windows 客户端。修法：**改实现、不动断言**——新增 `_ANY_SEP_RE`/`_ABS_FORM_RE`/`_WINDOWS_ABS_RE`/`_split_fragments`/`_is_foreign_absolute`，绝对与 `..` 判定同时覆盖两套分隔符；`resolve_within` 在 POSIX 宿主对含 `\` 的入参再作一次“反斜杠也是分隔符”的 containment（否则 `..\evil` 会被当作单个合法文件名而绕过穿越检查）；`safe_filename` 的 basename 改按分隔符切分取末段。保留 Windows 宿主对 `C:\...` 绝对入口的宽容（否则破坏 `/api/files` 回传契约）；测试面**拓宽** 4 例并注明不得改为 `skipif` 只跑一边。证据层级诚实：Windows 本地根 session **753 passed** / agent-core **278 passed** / 联邦 **152 passed** / governance **161 passed**，**POSIX 本机不可验证**（无 docker、WSL 未装分发），以此前失败的 CI 复验为准。
- **Batch 4 ① 单一实现（kernel）**：`agent_core.guardrails.errors` 新增 `mask_exception_for_client(exc, *, logger=None, context="", message=SANITIZED_5XX_MSG)`——自行 catch 的出口取固定文案的**脱敏边界点**。为何必需：`install_error_handlers` 只兜得住「未捕获异常 → 500 信封」，而 SSE 帧（状态码 200 已发）与手写 `JSONResponse` 它兜不住；`exc` **不参与返回值**（任何从异常消息派生的字段都会重开泄漏面），日志行内部用 f-string 而非 `%s` 惰性格式化，以同时兼容 std logging 与 loguru。
- **Batch 4 ② 站点收敛（6 处）**：exhibition `skill_loader/app.py` 3 处（CodeQL 所标的 3 条：chat 兜底 500 / invoke httpx 502 / health 探活 502）+ `skill_loader/agent.py` 工具 502 body（CodeQL 未标，但经 `/api/chat` 的 `tool_calls[].result_summary` 回传客户端，属同源）+ agent_server `api/query_router.py` 的 SSE `error` 帧 + knowledge-service `api/query_router.py` 与 `query_process/agent/nodes/node_answer_output.py` 两处 SSE `ERROR` 帧。保留项及理由：health 增加 `error_type=type(e).__name__`（类名不含消息，运维定位必需）；`/api/invoke` 保留 `url`（`/api/config` 已暴露同一 `WAREHOUSE_BASE_URL`，不属新增泄漏面）。
- **Batch 4 ③ 强制门禁（P8，三层补齐）**：`scripts/lint_architecture.py` 新增不变量——`applications/**` 下含 HTTP/SSE 出口标记（路由装饰器 / `JSONResponse(` / `HTTPException(` / `push_to_session(` / `sse_pack(` / `_sse(` 等）的模块，行内含异常消息级插值（`str(e)` / f-string `{e}` / `traceback.*`）即失败。放行四类：注释行、`logger.*` 行（异常全貌的合规去向）、仅类名写法（先剔 `type(x).__name__` 再判消息，故 `类名: 消息` 混写仍命中）、4xx 客户端错误回显（D-2=A：不动各 app 现有 4xx `{detail}` 信封，输入校验详情面向调用方自身输入）；白名单**故意置空并有单测钉住**（本不变量不允许静默例外）。**对 HEAD 版本回放**：命中 6 条与修复前站点逐条对应（规则非空转的直接证据）。
- **Batch 4 测试**：新增 kernel 6 例（`test_guardrails_errors.py` 固定文案/不泄漏/message 覆盖/日志仍写入/无 logger/`exc=None`）、`tests/governance/test_exception_echo_governance.py`（P8 正反例 + 当前树零违规 + 临时根埋探针）、`applications/exhibition-agent/tests/test_skill_loader_error_sanitization.py`（4 个出口 handler 直调，断言固定文案且内网主机/路径不出现在响应体）与 `tests/api/test_query_error_sanitization.py`（ASGITransport 驱 `/query`，断言 error 帧为固定文案且无 `NoneType`/`astream`，同时断言服务端日志仍在）。ks 两处站点**无行为级回归**：该仓 unit 套件 conftest 明文“刻意不依赖重型依赖”，导入 router/main_graph 会破其设计，改由 P8 结构门禁 + kernel 单测覆盖。
- **登记为范围外（P8 判定面之外，需先做通道分离再决策）**：nl2sql `agent/nodes/execute_sql.py:31` 的 `state["error"] = str(exc)` 会经 `SqlQueryResponse.error` 出到客户端，但**同一字段又是 `correct_sql` 节点的 LLM 纠错输入**——直接脱敏会削弱纠错回路；同类还有 federation `tools/*` 的 LLM 观察字符串与 `monitor.report_error(detail=str(e))` 审计遥测、agent_server `planners/graph.py` / `sql/pipeline.py` 的 StreamEvent error payload、exhibition `foundation/production_readiness_gate.py`。均非 HTTP 出口行内拼接，属“内部详情与对外文案未分道”的独立议题。
- **Batch 5（E 类、1 high）——把 dismiss 升级为根因消除**：`packages/agent-runtime/tests/test_skills_remote_dag.py:22` 原为 `assert "example.com" in result`，形状形似「URL 子串白名单校验」而为误报（该处实为 `as_remote_skill` 透传契约断言）。先按方案核实**生产面有无同款弱判断**：`packages/` 与 `applications/` 的非测试代码对「字面量含 `.com/.cn/localhost/://` 与 `in <url 类变量>`」两面均 **0 命中**（唯一相近的 `dsn.startswith("sqlite:///")` 是前缀而非子串判定），因此无可上收的单一实现。处置选择：不留在 GitHub 人工 dismiss（避免永久人工动作与注释债），改为**更强的等值断言** `result == "content from http://example.com"` 并补 `isinstance(result, str)`，零覆盖损失（改动方向是收紧，不触碰「不为消警放宽断言」红线）。
- **Batch 5 门禁决策（显式承认它是「三层齐备」的例外）**：不开 P9。理由：`lint_architecture.py` 只走 stdlib 正则、无类型推断，无法区分弱校验形态（子串包含）与**正确形态** `host in ALLOWED_HOSTS`（集合成员），而后者正是应被鼓动的写法；且生产面命中为 0，无存量需守。该维度继续交给 CodeQL 自身规则。同类形状 `test_model_router.py:230`（邮箱脱敏断言，CodeQL 未标）仅登记不改码。
- **核生产时的两条附带观察（不构成 E 类，登记为硬化候选）**：`agent_server/sql/pipeline.py:48` 的 `sqlite3.connect(f"file:{unquote(path)}?mode=ro", uri=True)` 若 `path` 解码后含 `?`，`mode=ro` 会落入首个参数的值而静默失效（只读双保险退化为一层；当前 `path` 源自服务端配置非请求入参，不列为可利用漏洞）；同文件 `:65` 的 `sqlite:///` 前缀判定属可接受写法。
- **未动项**：代码面五批已收完（A/B/C/D/E 均已修或定性），**open 告警归零需 GitHub 重扫确认**（本机无 CodeQL CLI）；仍需人工：`gateway/gray.py:40` 与 kernel #38/#39 的 dismiss（附证据）、部署时配 `AGENT_PLATFORM_SECURITY_PEPPER` 并先 dry-run 执行 `scripts/migrate_thread_identity.py`。原列为人工候选的「若 A/C 仍报则补 CodeQL data-extension 将 `safe_join`/`resolve_within`/`mask_exception_for_client` 声明为 sanitizer」已经 PR 重扫的反向证据排除（无新增 A/C/E/D 告警），无需补。
- **提交与交付状态**：Batch 1~5 已拆为 7 个 commit（`e488c96` 为此前的 Batch 1，本会话新增 `7bf3311` docs 方案 / `ba1b968` Batch 2 / `a586859` Batch 3 / `7cc9e1d` Batch 4 / `88f56c8` Batch 5 / `b845805` docs 收口）并 push 至 `fix/codeql-remediation-batch-1-5`，开为 **PR #33**（base `main`）。拆分取舍：`lint_architecture.py` 单文件承载 P6/P7/P8，因此**门禁层与其治理测试集中在 Batch 4 commit**（否则中间 commit 的树 `make ci` 会因引用尚未入库的 `fs.py` 而变红）。
- **PR #33 重扫结果与二次处置**：合入前 GitHub 已对本 PR 跑了一轮 CodeQL（PR 模式）。**无新增** `py/path-injection` / `py/stack-trace-exposure` / `py/incomplete-url-substring-sanitization` / `actions/missing-workflow-permissions`（A/C/E/D 的修改面在 CodeQL 眼里已无新问题，旧告警仍 open 只因默认分支未重扫）；新增仅 2 条 `py/weak-sensitive-data-hashing`，均落在 kernel 定义处：`guardrails/auth.py:78` 的 `hmac.new(pepper, secret, sha256)` 定为**误报**（输入是高熵 API Key、产物只做查表标识且每请求计算，换 scrypt/pbkdf2 只有延迟成本；**不改变量名躲检测器**），`:99` 的 `legacy_thread_id`（48bit 截断）形状**属实但不可消除**（需复算升级前旧会话身份）。两者均已写下可复核证据，但 **dismiss 未能脚本化**（`gh api` 对告警状态写入端点实测 HTTP 404，`PUT`/`PATCH` 两种动词与 `refs/heads/main` 告警均同，而 `GET` 正常 200；后经 `gh api -i` 响应头对比确证为令牌缺 `security_events` scope（GitHub 对 scope 不足统一回 404 而非 403）），仍需在 Security 面板手工执行（或先 `gh auth refresh -s security_events` 再走 API）；建议文案已同步入库（模块 docstring + 方案「PR #33 实测重扫结果」节）。
- **二次重扫（`c8e512e`+`45373dd`）无新增告警**：`ci`（push/PR 两事件）、`ha`、`Analyze (python|actions)` 均 pass；PR ref 上 open 仍只有 #38/#39 两条，**编号未因 kernel docstring 导致的行号漂移（78→92、99→117）而变动**——CodeQL 分组跟住了纯注释变更，本轮定调无需重开。CodeQL 检查仍 fail 的唯一剩余原因就是这两条未 dismiss（定性已同步回帖到 PR 上的两条 annotation，当前权限下能做的替代动作）。
- **新增 P6-2 门禁（约定 → 不变量）**：`legacy_thread_id` 的调用面原先只靠 docstring 约束（kernel 在 P6 白名单内，lint 拦不住新增调用点），现由 `scripts/lint_architecture.py` P6-2 锁死：除 kernel 定义处与 `scripts/migrate_thread_identity.py` 外出现调用即 CI 失败；补 4 个治理用例（单行正反例 + 当前树零违规 + 临时根埋探针验扫描面）。

## 隔离域加固：tenant 边界 / workspace 归属 / memories 双 scope（2026-09-27，分支 `feat/isolation-hardening`，`f072bc2..28877fc`）

> 归属说明：以下两节（09-27 隔离域加固、09-25 租户隔离收紧）原为 `v3` 分支历史条目，随 2026-10-01 `integration/v3-into-main` 合流**首次进入 `main` 时间线**。按 append-only 约定，不重写、不重排任何已有条目，仅加本行归属标记。

> 方案：`docs/adr/0006-isolation-dimension-contract.md`（已采纳）+ `docs/plans/plan-isolation-hardening-2026-09-27.md`（T9–T13）；episodic/procedural 部分依 `docs/plans/plan-memory-hardening-2026-09-27.md` T1。核心：`tenant_id` 为唯一安全边界（服务端解析、漏传 fail-fast 沿用 `_tenant_gate`），`workspace_id`/`user_id` 为归属维不单独承担隔离。

- **T9 corpus 补 tenant_id（`f072bc2`，W1）**：migration `006_tenant_corpus` 为 `chunks`/`sql_ddl`/`sql_docs`/`sql_examples` 加 `tenant_id`（`DEFAULT 'default'`）+ `(tenant_id, workspace_id)` 复合索引；`rag/store.py`、`sql/schema_store.py` 读写 SQL 成对带 tenant 谓词、消除「空 workspace = 全库召回」旁路；写入口（`/import`、`/sql/train`）收服务端租户（不收表单值）。
- **T10 workspaces 归属表（`28feae4`，W2/D4 方案 A）**：migration `007_workspaces` + 新模块 `agent_runtime/workspace_registry.py`；**复合 PK `(tenant_id, id)` 按租户命名空间化**（`workspace_id` 当前为客户端扁平串且共享 `'default'`，不能用全局唯一 `id` PK，否则跨租户撞名）；`resolve_workspace(tenant_id, workspace_id)->bool` 首次引用自动注册、越权 `assert_workspace_access` 抛 `WorkspaceTenantMismatch`；migration `009_workspaces_backfill` 幂等补注册现网 `(default, workspace_id)`。`import/sql/query_router` 使用前统一 `resolve_workspace`（读路径 best-effort）。
- **T11 knowledge-service 租户强制化（`0163fc6`，W4）**：`utils/tenant_utils.resolve_server_tenant()`——空 tenant → 服务端注入 `KNOWLEDGE_DEFAULT_TENANT_ID` + 审计（**选注入而非 422**：避免同步打断多个历史不传 tenant 的存量链路，同时关掉「空→不过滤=全库」真旁路）；删 `mongo_history_utils` 的 `if tenant_id else None` 回退；调用方审计：联邦 `tools/knowledge_tools.py::knowledge_retrieve` 改为下传请求链路租户（`api.context.get_tenant_context`），非 server 环境降级注入。
- **T12 隔离维度契约测试（`9c27c82`，W5）**：`tests/governance/test_isolation_dimension_contract.py`——迁移回放最终 schema 断言每张业务表含 `tenant_id`（系统/待判定表显式白名单+理由，人为建无 tenant 业务表→红）；AST 断言 `workspace_id =` 谓词必与 `tenant_id` 成对（已知误报源：docstring/日志，按“含表名 token + SQL 动词”过滤）。
- **T13 memories 双 scope（`e5566bf`，W3/用户拍板“画像层必须存在”）**：migration `008_memories_dual_scope`（`workspace_id`/`scope` 列 + 两索引 + user_id←workspace_id 回填）；内核 `typed.py` **新增** `remember_typed_scoped`/`recall_user_profile`（既有 5 动词签名不变、ADR-0004 向后兼容），workspace/user 两路各自 top-k 后按同一 `type_weight×importance×decay` 融合（不改评分公式，融合置于门面 `memory_backend.recall_typed`）；`MEMORY_DUAL_SCOPE` 渐进开关默认关=零变更，读路径双列兼容滚动升级窗口。
- **T1 episodic/procedural 补租户（`28877fc`，G1 / plan-memory-hardening T1）**：migration `010_episodic_tenant` 为 `episodic_memories`/`procedural_memories` 补 `tenant_id` + 复合索引，**procedural PK 命名空间化 `(tenant_id, name, version)`**（技能名由 `task_summary` 派生易跨租户撞名，仅加 WHERE 不改 PK 会写覆盖=假隔离）；`EpisodicStore`/`ProceduralStore` 及 InMemory/Pg 实现、`memory_sink`/`memory_decay`/`memory_seed`/`memory_types` 全链路带 `tenant_id`（`_tenant_gate` 必填 fail-fast）；**写路径租户源缺口修复**：`TrajectoryRecord` 加 `tenant_id`，`_persist_trajectory` 从 `plan.tenant_id` 填充；recall 路径 `MemoryRecallRequest.tenant_id` 下传并映射为 `MemoryRecallResult`。
- **迁移编号 006–010**：均 up/down 成对、`IF [NOT] EXISTS` 幂等、SQL 英文注释、LF 行尾；agent-core 零宿主依赖保持（`typed.py` 仅 stdlib；`workspace_registry`/执行记忆 store 落 agent-runtime，红线 1 无反向 import）。
- **未决 / 边界（诚实标注）**：① corpus/memories/episodic 存量 `DEFAULT 'default'` 回填为**目标库部署前置**——应用前须抽样确认无真实多租户混入（混则停工建归属映射，见 plan §8.2/§8.4），开发机无目标 PG 未执行；② agent_server→knowledge-service 真实多租户 tenant 下传、`/query` 服务端租户断言属跨服务契约变更，需另立 ADR（现注入策略下安全不 422）；③ HA 真实 PG 用例（`tests/ha/test_tenant_isolation_real_pg.py`：corpus/workspaces/dual-scope/episodic/procedural 跨租户）需 Linux CI `requires_pg` 跑，本机 skip。

> 验证（本机可跑，全绿）：根 438 / agent-core 219 / agent-runtime 580 / agent_server 44 / federation 142 / knowledge-service 235 / kefu 43 / nl2sql 18 / exhibition 343 / shared-schemas 28；`ruff check .` 0；`lint_architecture` + `check_doc_sync` 通过。唯一失败 `test_circuit_breaker_middleware_degrades` 为 v3 既有、与本工作无关。


## 租户隔离收紧 + HA 门禁语义 + CI 收窄（2026-09-25，`7e442c4..b77be4e`）

> 方案：`docs/plans/plan-p0-ha-tenant-fixes-2026-09-25.md`。外部审计（36 commits, c6b60a55）P0/P1 修复。评审修复（W-2）续见本节末。

- **⚠️ 破坏性行为变更（有意，不可逆）**：召回读谓词从过渡期 `tenant_id = ANY(%s)`（真实租户 + legacy `default` 桶）收紧为精确 `tenant_id = %s`（`7e442c4`）。真实租户升级后**不再读到**多租户上线前的历史记忆（v5 迁移已把历史行归并进 `default` 桶）；该数据仅 `default` 租户可见，或由管理员迁移工具重新归属。**回滚指引**：005 down 仅回滚列默认值、刻意不回滚数据（见该文件注释）——升级前如需保留跨租户历史可见性，须先完成数据归属迁移。配套：治理 fake 收紧为标量契约（泄漏形态直接断言失败）+ 新增真 PG 行为级回归 `tests/ha/test_tenant_isolation_real_pg.py`（legacy default 行对真实租户不可见 / default 租户仍可读 / 跨租户同 workspace 隔离），变异验证：谓词退回 ANY → 治理测试 4 failed。
- **`CapabilityReport.supports_tenant_isolation`**：新增能力声明字段并纳入 `as_dict()`/`/health`（pg-typed=true / vector=false），消除「调用方误以为已获得租户隔离」。
- **HA 门禁语义（skip→fail-not-skip）**：`tests/ha` 在 CI 环境（`CI`/`GITHUB_ACTIONS` 任一为 true）PG 不可用 = **FAIL** 而非 skip，杜绝「15 skipped 但 green」假信号；本地无 PG 保留 skip。普通 `make test` 根 session 以 `-m "not requires_pg"` 排除 HA 测试（归属 agent-platform-ha workflow）；conftest marker 路径判断修复 Windows 反斜杠兼容。
- **CI 收窄**：`ha.yml` 触发移除 `applications/**`（重型 HA 仅由 packages/tests/ha/脚本/配置变更触发）。
- **勘误**：下文 Warning#8 段描述的「过渡期 ANY 历史可读」为当时过渡契约，**已于本次收紧删除**，以本节为准。
- **W-2 补充（同日评审修复）**：内核 typed/store 五动词 + 宿主门面（agent_server longterm/memory_backend、federation semantic_memory）共 27 处 `tenant_id: str = "default"` 隐式缺省全部改为哨兵 `_TENANT_UNSET`（`agent_core/memory/_tenant_gate.py`）——**漏传即 `ValueError`**，不再静默落共享 default 桶。全链生产调用点已核实显式传租户（graph/planner/router/federation ContextVar），爆炸半径仅测试补显式 `tenant_id="default"`（67 处调用点，AST 脚本机械修复）。新增 AST 治理红线 `tests/governance/test_tenant_default_forbidden.py`（默认值形态回潮即 CI 失败；构造期配置类 `mongo_checkpointer`/`vector_backend` 白名单，其 tenant 语义矛盾另立任务）。

## workspace 顶层包名冲突全局治理（eval 消歧义 + P5 门禁，2026-09-25）

> 方案：`docs/plans/plan-workspace-toplevel-eval-disambiguation-2026-09-25.md`。背景：editable 安装以朴素 `.pth` 把成员源码根整体加入 `sys.path`，顶层包名 `eval` 被 agent_federation 与 knowledge-service 双重暴露，解析取决于安装顺序；前次 conftest 局部重绑补丁（c6b60a5）属散点止血，本次按「单一实现 + 全局装配 + 强制门禁」三层收口并撤销该补丁。

- **① 单一实现（ks 架构倒挂修复）**：`compute_config_hash`（含 `_RUNTIME_BASELINE`/`_sha256_hex`）从 `knowledge-service/eval/run_eval.py` 上收至新建 `knowledge_service/conf/config_hash.py`；`main.py` 不再 `from eval.run_eval import`（生产链路反向依赖评测 harness，且 wheel only-include 不含 eval/，打包部署必挂）；评测脚本与生产运行时共指同一实现。函数行为零变更。
- **② 消歧义（全局装配）**：`agent_federation/eval/` → `agent_federation/evaluation/`（`git mv` 保留历史；冲突引用面较小方），同步更新：包内 `from eval.*` 导入、docstring/用法路径、`tests/unit/test_eval_baseline.py`（`agent_federation.evaluation.run_eval`）、`pyproject.toml` ruff per-file-ignores、`.gitignore`（`evaluation/results/`）；live 文档同步（根 README/Makefile 注释/docs/TODO、federation production-action-plan 命令）。历史快照文档（CHANGELOG/AUDIT/PROPOSAL/analysis）不回改。全仓仅剩 ks 一个顶层 `eval` regular package，`.pth` 顺序敏感性消除。
- **撤销散点补丁**：`knowledge-service/tests/unit/conftest.py` 的 importlib 重绑 hack 恢复原样（止血措施随根因修复退场）。
- **③ 强制门禁（P5）**：`scripts/lint_architecture.py` 新增不变量——与 uv workspace members + 根包 wheel packages 同源解析暴露根，扫描源码根下含 `__init__.py` 的直接子目录，跨成员顶层包名重复即 CI 失败；当前树零违规无需白名单，自测：人为制造重名目录→退出码 1。

## 分支评审修复：Planner 租户传播 + SEMANTIC_MEMORY_TYPED 语义收口（2026-09-25，分支 `fix/v3-scheduler-tenant-isolation-20260924`）

> 来源：2026-09-25 对昨日新建分支的 CodeReview（Critical#2/#3、Warning#7）。

- **Critical#2 — Planner 租户传播**：`GraphPlanner`（4 处 Plan + execute 重建 plan_ctx）、`UnifiedPlanner` WORKFLOW 分支（Plan 身份字段 + kwargs 携带 tenant/workspace/user）、`AgenticPlanner`、`deterministic` MCP AgentState、`capabilities._run_general_qa` state 注入全部补齐 `tenant_id`；新增治理红线测试 `tests/governance/test_planner_tenant_propagation.py`（枚举全部 Planner 构造点，防漏传静默落共享桶）。
- **Critical#3 — 内核/federation 透传 tenant**：`agent_core.memory.store.MemoryStore` 协议五动词加 `tenant_id` keyword 参数，`PgMemoryStore` 透传内核 typed；`VectorMemoryStore` 显式声明不支持隔离（接口兼容）。federation `semantic_memory.py` 封装函数 + `main_agent_memory.py` 接线经 `api.context` ContextVar 取租户透传。
- **Warning#7 — 开关语义收口（WS-1）**：`agent_server/memory/longterm.py` 删除 `maybe_consolidate()` 中残留的 `SEMANTIC_MEMORY_TYPED` 栈门控（与读写路径对齐：该开关自 WS-1 起只在内核控制召回加权融合，不控栈选择；记忆总开关为 `SEMANTIC_MEMORY_ENABLED`），消除“读写不受控、巩固受控”分裂；模块/函数 docstring 与过时注释同步收口。测试：`test_maybe_consolidate_noop_when_disabled` 按新语义改写为 `test_maybe_consolidate_not_gated_by_typed_switch`（门禁：开关关闭时有池仍须触发巩固）+ 新增 `test_maybe_consolidate_noop_without_pool`（无池空操作），断言未收窄。
- **Warning#8 — v5 迁移可回滚 + 历史行过渡读**：新增 `005_memory_tenant_enforcement.down.sql`（仅回滚列默认值，刻意不回滚数据并在注释说明不可逆理由）与 `004_memory_tenant_id.down.sql`（对称 DROP，对齐 002/003 惯例）；内核 `agent_core/memory/typed.py` 召回读谓词改为过渡期 `tenant_id = ANY(%s)`（`_read_tenant_scope` 含 legacy `default` 桶，user_id 隔离维度不变），修复升级后带真实租户的请求读不到多租户上线前历史记忆的问题；删除路径（consolidate/forget）仍精确匹配不跨桶，收敛后可收紧。测试：新增 `TestTenantMigrationsRollback`（v4/v5 down 守卫）与 agent-core 读作用域/删除精确性 3 用例。**【2026-09-25 勘误】过渡读契约已收紧删除（读谓词精确 `= %s`，`_read_tenant_scope` 已删除），见顶部「租户隔离收紧」节。**

## MCP SDK 真实接入（2026-09-22）

> `mcp_client.py` 的 MVP 桩（`_invoke_tool` / `_discover_tools` / `_connect_*`）替换为真实 MCP SDK 调用，MCP 工具可经 stdio / SSE transport 真正连接、发现、调用。
> 验证：91 passed（agent-runtime）/ 361 passed 15 skipped（根）/ ruff 0 error。

### 改动

- **`_connect_stdio`**：`StdioServerParameters` + `stdio_client()` async ctx → `ClientSession(read, write)` → `session.initialize()`，返回 `(AsyncExitStack, session)`。
- **`_connect_sse`**：`sse_client(url)` async ctx → `ClientSession` → `initialize()`，同上。
- **`_discover_tools`**：`await session.list_tools()` → `[t.name for t in result.tools]`。
- **`_invoke_tool`**：`await conn.session.call_tool(tool_name, params)` 返回 `CallToolResult`（替换原 mock dict）。
- **`_reduce_result`**：处理 `CallToolResult.content`（`TextContent.text` 提取），`is_error=True` 时 raise `RuntimeError`（`call_tool` 捕获后返回 `McpToolResult(success=False, error="TOOL_RETURNED_ERROR")`）。
- **`close_all`**：`await conn._exit_stack.aclose()` 按 LIFO 关闭 session → transport。
- **`_MCPConnection`**：新增 `_exit_stack: AsyncExitStack | None` 字段。
- **`pyproject.toml`**：`agent-runtime` 新增 `[project.optional-dependencies] mcp = ["mcp>=0.9"]`。

### 测试

- 新增 `test_mcp_client_real.py`（13 例）：`_reduce_result` 处理 `CallToolResult` / `is_error` / 截断 / dict 兼容 / 纯字符串；`_invoke_tool` 真实调用 + SDK 缺失降级；`_discover_tools` 真实 `list_tools`；`close_all` 关闭 `AsyncExitStack`；`call_tool` 集成（`is_error` → 失败 / `TextContent` → evidence）。
- 现有 `test_mcp_skill.py` 8 例全绿（手动注入 `_MCPConnection`，不经 `connect_all`，不受影响）。

## Plan-F 架构收口 + Skill 体系完善（2026-09-21）

> Plan-F 4 个演进方向全量闭合，Skill 注册体系完善，沙箱代码执行落地。
> 验证：534 passed / 15 skipped / eval 15/15 = 100% / ruff 0 error。

### Plan-F 演进方向闭合

- **Plan.notes → 显式字段**（`36a3c0d`）：删除 `Plan.notes` 万能字典，所有字段提升为 Plan 显式字段（session_id/planner_name/constraints/kwargs 等），execution_graph.py 读取路径全部切换。PlannerContext 修复重复 `question` 字段 bug。
- **Dynamic Agent 纳入 Skill 体系**（`e477397`）：`AgenticPlanner.execute()` 加 `runtime.execution()` + `skill_guard("agentic")` 包裹，与 `arun()` 对称。agentic 执行受统一组合治理（步数/深度/循环），`SkillCompositionError` 直接抛出。
- **Workflow Definition → Workflow Skill 编译**（✅ 已实现）：`compile_workflow()` / `load_workflow_yaml()` / `discover_workflows()` 全部就绪，`agent_server/main.py` 启动期自动加载 `workflows/*.y*ml`。
- **SkillRegistry/SkillRuntime 分离**：暂缓（"边界出现再拆"原则，当前仅 timeout + 契约校验两个边界）。

### Skill 注册体系完善

- **MCP 工具自动注册**（`c472d59`）：`register_mcp_skills()` 把 MCPClientManager 发现的每个工具编译为 `SkillKind.REMOTE` Skill，命名 `mcp.{server_id}.{tool_name}`。启动期自动注册，Planner 经统一 `discover()` / `delegate()` 入口。
- **沙箱代码执行**（`7fcf303`）：`SandboxExecutor` 双后端（Docker 优先 subprocess 降级）。Docker 安全措施：`--rm --network=none --read-only --tmpfs /tmp --memory=512m --cpus=1 --security-opt=no-new-privileges --user=nobody`。注册为 `code_execution` Skill。
- **Planner 路由到沙箱**（`bf1f44c`）：启发式路由增加 `code_execution`（优先级最高），`_extract_code` 从用户输入提取代码块（支持 ` ```python ... ``` ` 格式），graph.py 增加代码执行节点。eval golden 15 条（含 3 条 code_execution）。

### Skill 注册体系终态

| 函数 | 类型 | 用途 |
|------|------|------|
| `as_function_skill()` | FUNCTION | 进程内确定性函数 |
| `as_agent_skill()` | AGENT | 本地 subagent（LLM self-reasoning） |
| `as_remote_skill()` | REMOTE | 远程子服务（HTTP / Agent Protocol） |
| `compile_workflow()` | WORKFLOW | YAML 声明式工作流编译 |
| `register_mcp_skills()` | REMOTE | MCP 工具自动注册 |
| `as_sandbox_skill()` | FUNCTION | 沙箱代码执行（Docker/subprocess 隔离） |

## Runtime 治理路线图全量闭环（2026-08-21）

> `docs/operations/runtime-governance-roadmap.md` P0~P5 全区段落地；`docs/tech-debt-hardcoded-logic.md` TD-1~TD-14 全部闭环。
> 验证：ruff 0 error / 架构 lint 通过 / 根 tests **541 passed**（原 import 失败目录已修复）/ 联邦 unit **92 passed** / kefu **8 passed** / eval **12/12 = 100%**。

### 计量闭环（P2）

- **P2-1 tokens/cost 聚合器**：`ExecutionContext` 新增 `tokens_used / cost_used / max_tokens / max_cost` + `record_usage()`（超限抛 `SkillCompositionError`）；`PlannerRuntime` 透传配置。
- **P2-2 llm client 计量点**：`FallbackChatModel` / `LangChainFallbackModel` 抽取 `usage_metadata`（含 `response_metadata` 兜底）→ `on_usage` 回调；`PlannerRuntime` 装配期接线到当前 `ExecutionContext`（contextvars 按 task 隔离，边界外静默丢弃）；invoke/ainvoke/stream/astream 四路径外发；`status` 事件带累计 tokens/cost。

### Trajectory（P3）

- **P3-1 持久化**：新增 `agent_runtime/trajectory/`（TrajectoryRecord/TrajectoryStep + `TrajectoryStore` 契约 + `InMemoryTrajectoryStore`/`PgTrajectoryStore`）；`execute_plan` 末尾 `_persist_trajectory`；宿主装配期 pool 非 None 时注入 PG 实现。
- **P3-2 Replay**：`trajectory/replay.py`——`replay_trajectory` 复用 `execute_plan` 真实执行链，报告五类 divergence（order / extra_call / missing_call / result_change / error_change）。

### 分布式 / 治理（P4）

- **P4-1 可插拔 session lease**：`LeaseBackend` 协议 + `InMemoryLeaseBackend`（默认快路径）+ `PgAdvisoryLeaseBackend`（`session_leases` 表单飞授权 + TTL 过期 + 双写本地镜像）；`Coordinator(lease_backend=, lease_ttl=)` 注入式。
- **P4-2 架构约束 lint**：`scripts/lint_architecture.py` 检测白名单外 `registry.execute()` 直调，串入 `make lint`。
- **P4-3 coalesce 诚实改名**：策略枚举仅保留 queue/reject。

### 语义循环检测（P5）

- **P5-1 TrajectoryFingerprint**：`_fingerprint`（skill + 归一化 kwargs，键序无关）重复指纹抛 `SkillCompositionError`；`enable_loop_fingerprint` 默认关闭防误伤合法重放。

### 技术债收尾（TD）

- **TD-1** kefu 意图路由验证：确认真实复用 `agent_core.intent`（回归测试锁定）；**TD-3/TD-4** 由 WS-6 隐式解决；**TD-5** 阈值参数化（`ITEM_CONFIRM_HIGH/MID_THRESHOLD`）；**TD-7** 路由特征词外置 `route_hints.json`；**TD-8** longterm prompt 泛化；**TD-9** eval 超参统一读 yaml；**TD-10** admission 状态常量 `ADMISSION_*`（含 SQL 语法修复）。

### 其他（同日提交）

- **§20 Workflow DSL**：YAML 声明式 Workflow 编译为 Skill + Workflows 目录自动发现注册。
- **UnifiedPlanner**：graph/workflow 统一分发；**PG durability**：admission/checkpoint/ownership/idempotency PG 后端套件。

## Agent 核心架构优化八工作流全量落地（2026-08-20）

> 实施计划：8 个工作流（WS-1 ~ WS-8），按 P0 → P1 → P2 推进。
> 原则：**不推倒重来，先接线、再收敛、最后清理**；每个 WS 独立可交付。
> 验证：ruff 0 error / 根 tests **484 passed** / 联邦 unit **89 passed** / kefu **8 passed** / eval **12/12 = 100%**。

### WS-1（P0）记忆子系统统一门面

- **`packages/agent-core/agent_core/memory/store.py` 新建**：`MemoryStore` Protocol（五动词 `recall / remember / consolidate / forget / probe`）+ `CapabilityReport` dataclass（宿主 `/health` 可直接序列化）。
- **`PgMemoryStore`**：包装 `typed` 模块（宿主 psycopg 池，遵守 ADR-0003 单一连接源），embedder 构造注入，支持全部五动词，**pg 为唯一权威后端**。
- **`VectorMemoryStore`**：包装 `MemoryBackend`（Milvus / PgVector），仅 recall / remember；consolidate / forget 返回 0 / False（向量后端无类型列）。
- **`semantic.py` 门面降级为薄适配器**：`SEMANTIC_MEMORY_ENABLED` 单总开关控制，`SEMANTIC_MEMORY_TYPED` 保留但只影响加权策略（**WS-1 起默认开**，不再决定走哪条栈）。
- 宿主接线：`applications/agent_server/memory/memory_backend.py` 改经门面；`lru_cache` 后端工厂补 `reset_backend_cache()`。
- **测试**：扩展 `packages/agent-core/tests/test_typed_memory.py`、`tests/test_memory_backend.py`；新增 probe 测试（无依赖环境返回 enabled=False + reason，绝不抛异常）。

### WS-2（P0）Context Pipeline 接线：snapshot 消费 + compact 归一

- **snapshot 消费闭环**：`applications/agent_server/planners/graph.py` 消费 `execute_plan` 产出的 `StreamEvent(type="status", payload={"snapshot": ...})`——多轮时将 `task`/`execution` 段注入下一轮 prompt 头部，并按现有 thread 持久化机制落 checkpoint。
- **compact 归一**：`agent_server/agent/graph.py`、`planners/deterministic.py` 改经 `agent_runtime.context.compact`；旧 `agent_server/agent/compact.py` 标记弃用。
- **`ConversationContext.compacted` 回填**：`deterministic.plan` 压缩分支 `notes["compacted"] = True`，`execution_graph.execute_plan` 检测后回填 `ctx.conversation.compacted`，保持三层契约一致。
- **测试**：`tests/test_compact.py` 迁移扩展；新增 snapshot 注入回归 + compacted 回填测试（`test_execute_plan_compacted_flag_backfilled` / `_default_false`）；eval 12/12 不回退。

### WS-3（P1）可靠性原语收敛

- **`resilience.CircuitBreaker` 并发安全**：内部加 `threading.Lock` 保护 `allow()/record_*`，half_open 探测计数不再竞态；新增 `_half_open_inflight` 限制并发探测数（`max_half_open_probe`）。
- **统一状态常量**：内核暴露 `STATE_CLOSED / STATE_OPEN / STATE_HALF_OPEN`（`agent_runtime.circuit_breaker` 的 `"half-open"` 兼容别名保留一版）。
- **`llm/fallback.py` 降级状态机收敛**：`FallbackChatModel` 删除内嵌失败计数，改为**组合** `CircuitBreaker`（threshold→failure_threshold，cooldown→reset_timeout），可复位。
- **流式降级语义修正**：`stream/astream` 仅在「未产出任何 chunk」时才允许切备模型重放；已产出 chunk 后主模型失败 → 向上抛异常，docstring 明确契约。
- **测试**：扩展 `packages/agent-core/tests/test_resilience.py`（并发 allow/record 竞争用例）、`tests/test_llm_fallback.py`（中途流式失败 + breaker 组合用例）。

### WS-4（P1）可观测性统一事件出口

- **`packages/agent-core/agent_core/events.py` 新建**：`EventSink` Protocol + `EventBus`（多 sink 扇出、逐 sink 异常隔离、失败计数）。
- **四 sink 注册**：`CallbackSink`（回调订阅）、`WebSocketSink`（WS 推送）、`LegacyStreamSink`（旧 builtins.runtime 通道，首次命中触发 DeprecationWarning）、`OTelSpanSink`（OTel span 事件出口，懒导入 opentelemetry，无活跃 span 时静默 no-op）。
- **`monitor.py` 改造**：`ToolMonitor._emit` 改走 `EventBus` 扇出；`ToolMonitor()` 单例语义保留兼容，新 API 支持 `ToolMonitor(bus=...)` 构造注入。
- **测试**：`packages/agent-core/tests/test_events.py` 扩展多 sink 扇出 + 异常隔离 + OTelSpanSink（no-op / fake span 写入）用例；federation/kefu 既有 monitor 测试全绿。

### WS-5（P1）KernelConfig 与环境变量治理

- **`packages/agent-core/agent_core/config.py` 新建**：`KernelConfig` dataclass + 类型化 env 解析助手（`env_bool / env_int / env_float / env_str`，非法值警告并回退默认）；`env_database_url`（新名 `AGENT_PLATFORM_DATABASE_URL` 优先，旧名 `DEEPAGENTS_DATABASE_URL` 兼容 + DeprecationWarning）。
- **散点 `os.getenv` 全量迁移**：`memory/typed.py`、`memory/semantic.py`（5 处：VECTOR_BACKEND / MILVUS_URI / MILVUS_TOKEN / SEMANTIC_MEMORY_COLLECTION / TENANT_ID）改经 `env_str`/`env_bool`。
- **环境变量清单表**落入 `packages/agent-core/README.md`（变量名 / 默认值 / 所属模块 / 用途），后续新增 env 必须登记。
- **测试**：新增 config 解析单测；grep 确认无新代码直读旧变量名。

### WS-6（P2）意图 L1 分类器数据化与异步契约

- **`packages/agent-core/agent_core/intent/classifier.py`**：`_load_prototypes()` 加 `@lru_cache(maxsize=1)`（保留测试用 `cache_clear` 出口）；chitchat 关键词短链（`_CHITCHAT_STRONG` / `_CHITCHAT_WEAK`）外置到 `data/prototypes.json` 的 `chitchat_shortcuts` 段，代码只留读取逻辑 + 数据缺失兜底。
- **新增 `classify_l1_async(query)`**：`asyncio.to_thread(classify_l1, ...)` 包装，docstring 声明 `classify_l1` 为阻塞调用。
- 核查 `agent_federation/planners/agentic.py` 与 kefu 调用点，统一改走 async 入口。
- **测试**：`packages/agent-core/tests/test_intent.py`、`test_intent_l2.py` 全绿 + 数据外置后等价性用例。

### WS-7（P2）Tool/Skill 执行策略合并

- **`packages/agent-runtime/agent_runtime/skills/middleware.py`** 新增 `GuardMiddleware`：超时（`asyncio.wait_for`，async-native）+ 失败降级返回空结果，语义对齐 `guarded_invoke`；新代码应优先挂本中间件而非再包 `wrap_tool`。
- **`agent_core.tools.guarded`** 与 **`ToolRegistry`** 标记为维护模式：docstring 声明新代码用 SkillRegistry + middleware；zhanggui-zhiku 的 fanout 调用点迁移列入后续专项。
- **`guarded_invoke`** 内 8 线程池保留（同步工具仍需），补"超时后线程不可取消、仅放弃等待"显式文档。
- **测试**：`tests/test_graph_planner.py` 风格新增 GuardMiddleware 超时/降级用例。

### WS-8（P2）LLM 客户端缓存治理

- **`packages/agent-core/agent_core/llm/registry.py`**：`_CLIENT_CACHE` 改为上限 64 的 LRU（`OrderedDict`，零依赖）；cache key 中 `api_key` 替换为 `sha256(api_key)` 摘要，密钥不再常驻缓存键。
- **`packages/agent-core/agent_core/llm/protocols.py` 新建**：`ChatModel` Protocol（`invoke / ainvoke / stream / astream`），`FallbackChatModel` 的 primary/fallback 类型标注改用它。
- **`fallback_lc.py`** 不动（组合结构已正确）。
- **测试**：新增 LRU 淘汰与 key 哈希单测；`tests/test_llm_fallback.py` 全绿。

### 完成审计补漏（实施后逐项核对 spec 发现并修复）

| 遗漏项 | 工作流 | 修复 |
|---|---|---|
| `OTelSpanSink` 未实现 | WS-4 | `events.py` 新增类，懒导入 opentelemetry，无活跃 span 时静默 no-op |
| `semantic.py` 散点 `os.getenv` 未迁经配置层 | WS-5 | 5 处改经 `env_str`；新增 `env_str` 助手函数到 `config.py` |
| `ConversationContext.compacted` 回填未接线 | WS-2 | `deterministic.plan` 压缩分支标记 `notes["compacted"]`；`execute_plan` 回填 `ctx.conversation.compacted` |
| `SEMANTIC_MEMORY_TYPED` 默认值应改开 | WS-1 | `config.py` / `typed.py` 默认从 `False` 改 `True`；修复 `test_longterm_h` 中被旧默认值掩盖的 patch 错位 |

## 架构审核落地（2026-08-19 晚）—— Planner/Skill/Runtime 收口

- **PlannerRuntime per-request 隔离（P0）**：`_steps`/`_call_stack` 由实例 mutable state 改为 `contextvars.ContextVar`——异 session 并发互不干扰、同 session 串行共享预算，修复单例注入下「一次执行的预算被并发请求耗尽」的跨请求污染；`max_steps`/`max_skill_depth` 保持不可变配置。
- **配套测试语义修正**：`test_planner_governance.py` / `test_agentic_planner.py` 原「跨多次 arun 累计步数」断言即旧 bug 行为，改为「单次执行内嵌套超限 + 执行结束预算复位」（新增 `test_guard_budget_resets_after_execution`）。
- **SessionCoordinator 语义明确（P0）**：docstring 声明 **process-local 单实例**（`_active/_queues/_conditions` 均 asyncio 进程内状态），多副本下「同 session 串行」不成立；演进方向：分布式 lease / durable execution 持有 ownership（本期不做）。
- **Skill 入参契约真正执行（P1）**：`SkillRegistry.execute()` 新增 `_validate_input()`——`required` 存在性 + `properties` 类型校验，缺 schema 向后兼容、不拒绝注册方注入参数（mcp 的 state/mcp_manager）；传错参数抛明确 `SkillExecutionError` 而非内部 Python exception。新增 3 测试。
- **术语精确化**：`SkillKind.WORKFLOW` 注释与架构文档统一「Static DAG → Workflow（Static/Conditional）」，LangGraph 明确为执行实现。
- **演进方向留档（暂缓重构）**：SkillRegistry/SkillRuntime 分离——写入 `docs/plan-f-single-runtime-multi-planner.md`，按「边界出现再拆」原则执行。`Plan.notes`→显式字段 ✅ 完成、Dynamic Agent 纳入 Skill 体系 ✅ 完成、Workflow Definition→Workflow Skill 编译 ✅ 已实现（2026-09-21）。
- **测试**：根 tests 180 passed（governance 7 + capability registry 16 含契约测试）/ 联邦 unit 89 passed（零回归），ruff 0 error。

## Plan-F 收尾（2026-08-19）—— Capability→Skill 全量 rename

- **命名统一（待用户确认范围：全量重命名）**：将 `agent_runtime/capabilities/` 体系重命名为 `agent_runtime/skills/`，符号 `Capability`→`Skill`、`CapabilityKind`→`SkillKind`、`CapabilityRegistry`→`SkillRegistry`、`CapabilityNotFoundError`→`SkillNotFoundError`、`DuplicateCapabilityError`→`DuplicateSkillError`、`as_function/agent/remote/dag_capability`→`as_function/agent/remote/dag_skill`。
- **保留项（语义不同，不乱改）**：`app/schemas.py` 的 `Capability = Literal[...]`（路由决策选中的能力名）与所有 `decision.capability` / plan payload 的 `capability` key / StreamEvent 的 `capability` payload——它们是「路由决策结果」，非治理 Skill，保持原样。
- 波及 `app/`、`agent_federation/`、`tests/`、`eval/` 共 27 个 `.py`（已排除无关 `dialogue-framework` 巧合命中）；用脚本批量 rename（符号级 + 目录重命名），避免 Unicode 匹配误差。
- **测试**：根 tests **322 passed**（零回归）；`tests/test_capability_registry.py` 13 passed；联邦 unit 87 passed；lint 0 error。

## Plan-F 收尾（2026-08-19）—— WS evidence/memory 桥接闭环

- **`agent_federation/planners/agentic.py`**：`execute()` 现把 `_execute_agent_core` 运行期经全局 `monitor` 发射的运行时事件桥接为 `evidence` StreamEvent（route → evidence* → answer）。新增 `_monitor_event_to_stream_event()`（只读转换，保留 event/message/data 原文）+ `_subscribe_monitor()`（用现有 `monitor.on/off` 临时订阅 `assistant_call`/`tool_start`/`tool_outcome`/`session_created`/`task_result`/`circuit_state_change`/`error`，每个 execute 用自己的闭包+列表，并发安全）。
- **不破坏黑盒契约**：`run_deep_agent` 的 `_execute_agent_core` 内部零改动，monitor 全局 WS 通道（ConnectionManager）不受影响；仅 execute 路径的 StreamEvent 流更丰富（WS 客户端可见子 agent 调用/工具证据/记忆上下文建立）。
- 原 WS 出口统一收尾（第 24 行）标注的「evidence/memory 桥接留作后续」**已闭环**。
- **测试**：扩 `tests/unit/test_agentic_planner.py`（+2 例：execute 桥接 monitor 事件为 evidence；异常路径订阅必注销防回调泄漏）；联邦 unit 87→87（含新增 2 例，原 85 + 新加 execute 桥接共 87）passed。

## Plan-F 收尾（2026-08-19）—— 真实 R1 基线（环境限制，待有 key 环境执行）

- **`agent_federation/eval/run_eval.py`**：`--baseline` 新增前置检查 `_require_real_llm_key_for_baseline()`——`OPENAI_API_KEY` 缺失/占位（test-key/x/sk-test 等）时直接 `sys.exit(2)` 并打印可执行指引，避免在无 key 环境产出垃圾 `fed_latest.jsonl`。
- **当前状态**：开发环境无真实 LLM key，`fed_latest.jsonl` 真实基线**待在有 key 环境执行**——`uv run python -m agent_federation.eval.run_eval --baseline eval/fed_latest.jsonl`；R1 漂移门禁的**比对逻辑本身无 LLM 依赖**，已通过 `tests/unit/test_eval_baseline.py`（4 例）覆盖，可作 CI 门禁。
- **Boundary**：仅加前置护栏，不改 `--compare/--fail-below` 比对语义。

## Plan-F Phase 3 联邦侧收尾（2026-08-19）—— 双轨真正闭环

- **`agent_federation/planners/agentic.py`**：新增 `AgenticPlanner.arun(question, workspace_id, runtime, main_agent=None) -> str`——与 `execute`（供 app SSE 产出 StreamEvent）并存；`async with runtime.skill_guard("agentic")` 包裹 `_execute_agent_core`，将组合治理（max_skill_depth/max_steps）落地联邦主链路；`main_agent` 透传保留动态 agent 选择能力（不进统一协议）。
- **`agent_federation/planners/__init__.py`**：新增 `get_planner_runtime()` 模块级单例（联邦无 FastAPI app.state 注入先例），治理参数取 `FED_MAX_SKILL_DEPTH` / `FED_MAX_STEPS`（默认 4/20，与 PlannerRuntime 默认及 app/config 对齐），`registry=None`（联邦 agentic 不查能力注册表）。
- **`agent_federation/agent/main_agent.py`**：`run_deep_agent` 把 `singleflight(_execute_agent_core, ...)` 改为 `singleflight(AgenticPlanner().arun, ..., get_planner_runtime(), selected_agent)`——保留 singleflight 缓存击穿防护 + 全部副作用链（guard/intent/cache/memory/monitor/remember_episodic/SemanticCache），仅「最终执行」委托给 Planner 协议 + 治理；eval/WS 的 monitor 事件契约零破坏。
- **Boundary**：`deep_agent` subagents 委派机制（`_build_subagents` / `create_deep_agent`）保持不动——Plan-F 目标是「编排收敛」而非「重写委派」，避免破坏现有行为。
- **测试**：扩 `tests/unit/test_agentic_planner.py`（arun 经治理复用 + main_agent 透传 + 步数超限抛 `SkillCompositionError`）；新增 `tests/unit/test_run_deep_agent_planner.py`（run_deep_agent 经 planner.arun 走通 + monitor 上报保留）；联邦 unit 81 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F R1 漂移门禁收尾（2026-08-19）—— 双跑 eval 基线闭环

- **`agent_federation/eval/run_eval.py`**：新增 `--baseline <path>`（本次结果快照为行为基线，只落 `id`/`routed_agents`/`routing_score`/`rubric_rate`，不存 answer 全文）+ `--compare <path>`（逐项对比漂移：exact/jaccard/rubric 退化 + 缺失题，报告漂移率）+ `--fail-below`（漂移率超阈值退出码非零，可作 CI 门禁）；`save_baseline`/`compare_baseline` 抽为独立纯函数。
- 纯数据结构对比，无 LLM 依赖，CI 可守；用法：先 `--baseline` 锁切换后基线 → 后续 `--compare --fail-below 0.05` 守门禁。
- **测试**：新增 `tests/unit/test_eval_baseline.py`（4 例：baseline 快照剥离 + exact/jaccard/rubric 退化 + 缺失题 + clean 无漂移）；联邦 unit 85 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F WS 出口统一收尾（2026-08-19）—— 双轨流式事件同构

- **`agent_runtime/planner/protocol.py`**：新增 `serialize_stream_event(event) -> dict | None`，作为 app(SSE) / 联邦(WS) **共享的单一映射**，消除双轨出口 schema 漂移源。
- **`app/api/routes.py`**：`_stream_event` 委托 `serialize_stream_event`（输出结构不变，消除 app 内硬编码映射副本）。
- **`agent_federation/api/server.py`**：`/ws/{thread_id}` 从 echo/pong 升级为——收 `{"type":"query","text":...}` → `AgenticPlanner.execute` 产 `StreamEvent` → 逐条 `send_json(serialize_stream_event)` → 收尾 `{"type":"done","thread_id","answer"}`；非 query 合法 JSON 回退 pong（保留旧兼容）；`/api/task` 不动。
- **Boundary**：仅统一「事件 schema 出口」，不重写联邦 WS 鉴权/并发/前端协议；evidence/memory 桥接（monitor→StreamEvent）已于同日后续收尾闭环（见上方「WS evidence/memory 桥接闭环」）。
- **测试**：新增 `tests/unit/test_ws_stream.py`（2 例：query 流式收 route+answer+done；非 query 回退 pong，mock execute 免 LLM）；联邦 unit 87 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F 单 Runtime 多 Planner 启动（2026-08-19）

- **方案文档** `docs/plan-f-single-runtime-multi-planner.md`：双轨收敛共识落档——「单 Runtime + 多 Planner」取代 plan-e 的「收敛」表述。含 K1–K5 卡点修正、R0 控制权冲突风险、P1–P5 五个落地契约点、Phase 0–3 路线图。
- **`shared-schemas/shared_schemas/thread.py`**：统一线程状态契约 `ThreadState`（messages 序列化 dict + metadata 编排状态 + version）——双 Planner 共享 checkpoint 的状态兼容基础（契约点 P2）。
- **`agent-runtime/` 新包**（uv workspace 新成员）：运行时中间件层。首个迁移单元 = admission：`app/infra/admission.py` → `agent_runtime/admission.py`，`AdmissionDecision` 类型 → `agent_runtime/schemas.py`；`app/schemas.py` re-export 兼容旧引用，`app/main.py` 改从 `agent_runtime` 引用。
- **验证**：根 tests **261 passed**（排除 wenda/dialogue 既有环境缺失目录）；迁移相关 test_router + test_input_guard_graph 8 passed；`app.main` import ok。
- **Phase 0 完成（同日）**：剩余 8 个运行时模块全部迁入 `agent_runtime.*`——cache / circuit_breaker / coordinator（CoordinationDecision）/ revert（RevertResult）/ mcp_client（McpServerConfig/McpToolResult）/ otel / tracing / db。`app/schemas.py` 对 4 个运行时类型 re-export 兼容；`app/infra/` 9 模块全部删除，仅留空包占位（退役标记）。
  - **配置依赖倒置**：`db.init_pool(database_url, db_pool_max_size)` / `db.ensure_schema(pool, vector_dim)` / `tracing.get_langfuse_callbacks(public_key, secret_key, host)`——agent-runtime 零依赖 `app.config`，参数由 app lifespan / scripts 从 Settings 注入。
  - 调用点全量更新：app 内部 8 文件 + scripts 3 个 + tests 4 个，改从 `agent_runtime.*` 引用。
  - 验证：根 tests **261 passed（零回归）**，`app.main` import ok，lint 0 error。
- 不做（遵循不过度设计）：`db.py` 的 `SCHEMA_TEMPLATE` 已随迁移归位（建表职责属 agent-runtime 初始化）；联邦 3 个 unit error 为 `deepagents` 改名遗留（测试文件仍 import PyPI `deepagents` 包），与本变更无关。

## Plan-F Phase 1 能力层中立化（2026-08-19）

- **`agent-runtime/agent_runtime/capabilities/` 新包**：`Capability` + `CapabilityRegistry`（注册/发现/统一执行入口，超时边界收敛于 execute）+ 三执行器工厂——`as_function_capability`（进程内 async 函数）/ `as_agent_capability`（subagent dict → lazy `deepagents.create_deep_agent`，与联邦本地 fallback 同路径）/ `as_remote_capability`（远程子服务调用）。
- **`app/capabilities.py`**：装配 search/rag/sql/mcp 四能力为 function 型注册项（惰性单例）；`app/agent/graph.py` 四节点改经 `registry.execute(...)`——能力层中立化首个生产路径验证。
- **测试**：`tests/test_capability_registry.py` 7 例（注册/发现/重复注册/未知能力/超时/三执行器）；根 tests **268 passed**（261 基线 + 7 新增，零回归），lint 0 error。
- 不做（遵循不过度设计）：联邦 `main_agent.py` 委派路径未改（deep_agent subagents 机制属 Phase 2 Planner 协议切换范围）；`Capability.metadata` 仅留扩展位不预填；MCP 能力签名依赖 state+manager 以 kwargs 透传承载，不强行重构为 query 形态。

## Plan-F Phase 1.5 Skill 契约升级（2026-08-19）

- **`agent-runtime/agent_runtime/capabilities/registry.py`**：`CapabilityKind` 增 `WORKFLOW`；`Capability` 增 `input_schema` / `output_schema`（JSON Schema dict，可空）；新增 `to_tool_schema()`（供 Agent 工具描述生成 + 入参契约显式化）。
- **`capabilities/dag.py` 新建**：`as_dag_capability(...)` → kind=WORKFLOW，把确定性 DAG 执行器封装为可注册 Workflow Skill（Static DAG Executor，对应 §4.1）。
- **`app/capabilities.py`**：定义 query/rag/general_qa 四套 JSON Schema 契约；`build_registry(graph=None)` 注入 graph 时注册 `general_qa` Workflow Skill（graph.py **包装非删除**），`get_registry` 惰性单例。
- **测试**：`test_capability_registry.py` 扩至 13 例（schema 契约 + WORKFLOW + general_qa 装配），零回归。

## Plan-F Phase 3 单 Runtime 成型（2026-08-19）

- **`agent_runtime/planner/protocol.py`**：新增 `SkillCompositionError` + `PlannerRuntime.skill_guard`（max_skill_depth=4 / max_steps=20 / 循环检测），仅 agentic 组合路径使用。
- **`app/memory/thread_persist.py` 新建**：`read_thread_messages` / `append_thread`——经 checkpoint aget_tuple/aput 落消息历史（channel_versions 推进 + new_versions 落 blob；空 answer/no checkpointer/thread 间隔离均正确 noop）。
- **`app/api/routes.py`**：`/query` 切 Planner 主路径（`PlannerContext`→`plan`→`execute`→StreamEvent→SSE 映射）+ graph 兜底 + 历史写回 checkpointer；新增 `_stream_event` 统一出口。
- **`app/main.py` / `app/config.py`**：lifespan 装配 `registry` + `planner_runtime`；配置增 `max_skill_depth` / `max_steps`。
- **测试**：新增 `test_planner_governance.py`（6）/ `test_thread_persist.py`（6）；根 tests **全量回归 322 passed（零回归）**，lint 0 error。
- 不做（遵循不过度设计）：WS 出口统一延后（app 现仅 SSE）；`version`/`risk_level`/`policy` 元数据暂缓（单实例无多租户分级诉求）。

## v2 Resilience 收敛（2026-08-19）

- **`agent-core/agent_core/resilience.py` 新增 `retry_async`**：异步指数退避重试原语（`max_attempts` 含首次、退避 `base*factor**(n-1)`、`exceptions` 过滤、可注入 `sleep`、支持同步/异步 `on_retry` 回调），与同步 `retry` 语义对齐。
- **`agent_federation/agent/async_subagents.py`**：`DelegatingSubAgent.ainvoke` 手写重试循环 → 内核 `retry_async`（行为等价：`max_attempts=RETRIES+1`、退避 `base*2**attempt`、成功即 `record_success`+返回、全败计入熔断并走本地 fallback），消除手写指数退避样板。
- **测试**：`test_resilience.py` 新增 8 例；agent-core 全量 146 passed；federation 契约测试 8 passed；行为等价验证 4 场景（首次成功 / 失败 1 次后成功 / 全败走 fallback / 熔断短路）。

> 不做的（遵循不过度设计）：Resilience Policy 三件套组合对象（Retry+Timeout+CB+Fallback）当前无真实「嵌套组合」调用点，待出现第 3 个组合需求再提取；`app/rag/rerank.py` / `zhanggui-zhiku` 的重试带 HTTP status-code 语义（429/5xx 才重试），与内核「按异常类型」语义不同，强行替换属过度设计。

## v2 TB 核销（2026-08-19）

- **TB-11 第一步落地（配置体系盘点）**：`agent_federation/README.md` 环境变量表重写 + `.env.example` 以源码为真相源全量盘点 80+ 开关（含共享内核 `agent_core.memory.*` 11 项）。修正 `SUBAGENT_RETRY_BASE` 默认值偏差（1.0→0.5，与 `async_subagents.py:153` 一致）；移除源码中已不存在的过时 `MYSQL_POOL_RESET_SESSION`；补全缺失开关：`KEFU_SERVICE_URL`/`KEFU_USE_ADAPTER`/熔断 `CB_*`×5/缓存 `KB_VERSION_*`×3/`TENANT_ID`/`RAGFLOW_*`/`EMBEDDING_DIM`/`DEEPAGENTS_DB_POOL_MAX`/`DATABASE_URL`/`EMBEDDING_API_KEY`。
- **审查核销**：优化 H（ADR-0004 阶段 1~3 已下沉内核 `agent_core.memory.typed`，D1~D5 全落地）、TB-9（意图分类收口内核 `agent_core.intent.classify_intent`，`intent_bridge.py` 单一真源）、TB-10（联邦已挂 typed 长期记忆 + 内核 checkpointer 三态）、TB-12（两轨缓存均实现 `BaseSemanticCache` 统计接口）状态已在 `docs/architecture-improvement-plan.md` 登记核销。
- 不做（遵循不过度设计）：agent_federation 配置全量迁移 pydantic-settings 属大 churn 且无真实复用需求，保留为长期项（待出现第 3 个配置消费方）。

## v2 分支修复记录（2026-08-16）

### 安全 / 护栏
- **#1** `app/agent/graph.py`：输入护栏拦截改为短路（`route:"blocked"` → `END`），拦截文案不再被 `synthesize_node` 覆盖；拦截不进记忆，避免原文落库。
- **#2** `app/agent/graph.py`：脱敏文本写回 `state.question`，下游路由/记忆均使用脱敏内容。
- **#4** 新增 `tests/test_input_guard_graph.py`：护栏拦截短路 / 脱敏传播 / guard 关闭透传 3 例回归。

### 工程 / 配置
- **#3** `pyproject.toml`：`ruff.lint.select` 显式固化 `["E4","E7","E9","F","I"]`，避免默认 select 漂移关闭 isort。
- **#7** `deepagents/requirements.txt`：补 `-e ../shared-schemas` 与 `sqlglot>=25.0`（非 uv 用户备选安装）。
- **#9** 核验：`FallbackChatModel` 默认 `failure_threshold=3`，降级阈值正确。
- **#11** `docs/architecture-improvement-plan.md`：「核验维持现状」记录项；原登记优化 A/B 要点2（`_validate_state`/`guard_middleware`）未实施已过时，参见下方「双轨技术债收敛」更正。
- **#14** 删除 `zhanggui-zhiku/uv.lock`，统一到 workspace 根锁。

### 核验维持现状（非缺陷）
- **#5** 路由结构化输出恒绑主模型，但 `decide_route` 已有启发式兜底，不阻塞。
- **#6** fallback `stream` 重播缺陷，app 链路未用 stream，待启用时再修。
- **#8** SQL 守卫 `max_rows`（默认 100）为有意的防护上限，非缺陷。
- **#12** `make type` 为 ruff 别名，非缺陷。
- **#13** `rag_query` 优先走 `AsyncSubAgent`，httpx 仅兜底，影响窄。
- **#15** logger 命名已规范（`__name__` + 顶层 `agent_core`），非缺陷。

### P4 双轨收敛（先前提交）
- P4.1 `shared_schemas` 契约断言（`AsyncSubAgent` 返回 `QueryResponse`）。
- P4.2 SQL 守卫下沉 `agent_core`（`deepagents/tools/sql_guard.py` 委托内核）。
- P4.3 `MemoryBackend` Protocol 抽象（`agent_core.memory`）。

### 技术债 TB 闭环（2026-08-16）
- **TB-4** `agent-core/agent_core/cache/base.py`：新增 `BaseSemanticCache` Protocol + `build_cache_key` 纯函数（sha256 of `intent|rewritten_query|kb_versions|tenant_id|gray_pct`），`deepagents` 复用，消除本地缓存键实现分歧。
- **TB-5** 语义缓存键契约固化（随 TB-4 一并收敛）。
- **TB-6** `deepagents/agent/async_subagents.py`：新增 `_normalize_response` + `_E1_CONTENT_ASSERT`，kefu 契约双向核验（形状 + 内容非空）；`kefu-service` 显式 `fallback=False`。
- **TB-8** `eval/run_eval.py`：加 `--require-llm`（环境不可达 SKIP 退出码 2）、默认 `--fail-below 0.8`；`Makefile` 评测改直接路径 `eval/run_eval.py`（避开 deepagents 同名模块冲突）。
- **TB-7** `docker-compose.yml`：为 `agent-platform` 补 healthcheck（TB-7 端到端冒烟可判定就绪）；`Makefile` 增 `compose-smoke`（需 Docker）；`scripts/smoke_memory.py` 提供无 Docker 的等价内存模式预热冒烟；说明见 `docs/tb7-smoke.md`。
- **TB-1** `dialogue-framework/shared/llm/core_adapter.py`：新增 `LLMCoreClient`，把 agent_core `BaseLLMProvider`（工厂协议）桥接为 DF `BaseChatClient`（运行时协议）；`BaseChatClient` 标记 `@runtime_checkable`，docstring 明确两者互补不合并。`langchain_client.py` 标注其 `FallbackChatModel` 即内核协议实现。
- **TB-2** `dialogue-framework/core/tracker_memory.py`：新增 `TrackerConversationMemory`，实现 agent_core `ConversationMemory` 协议（save/get_recent/clear/update），把 user/assistant 消息落进 `Tracker.events`；`Tracker.to_conversation_memory()` 桥接挂载。`dialogue-framework/tests/test_tb_bridge.py` 覆盖两协议桥接（3 passed）。

> 红线：dialogue-framework 不合并 / 删除，仅做协议对齐桥接（TB-1/TB-2 均满足，未改动 DF 自有数据结构与对外接口）。
> 至此 TB-1~TB-8 全部闭环。

### 双轨技术债收敛（2026-08-16 后续，commit 2bd215c + a6108c7）
- **优化 A 要点2** `app/agent/state.py` + `graph.py`：`AgentState.route` 由裸 `str` 枚举化为 `Literal["search","rag","sql","direct","mcp","blocked"]`（与 `graph.py` 条件分支键一一对应，非法路由值由 Pydantic 即时拦截）；新增 `_validate_state()` 入口校验（非空 `question`），在 `route_node` 调用。`tests/test_agent_state.py` 增 3 例。
- **优化 B 要点2** `deepagents/gateway/guard_middleware.py`（新增）+ `deepagents/agent/main_agent.py`：新增 `GuardMiddleware(AgentMiddleware)`，在 `before_agent` 钩子对入口 user 文本做 PII 脱敏改写 + injection 拦截；`_build_middleware()` 按 `GUARD_ENABLED` 开关注入（带失败降级），deepagents 视图 agent 默认经输入护栏。`deepagents/tests/unit/test_guard_middleware.py` 增 5 例。
- **TB-4 key 闭环** `app/infra/cache.py`：`_cache_write` 的 `cache_key` 由明文 `question.strip().lower()` 改为内核 `build_cache_key(intent="", rewritten_query=...)`，与 deepagents 共用同一 hash 逻辑（lookup 端纯向量命中，不受影响）。
- **U-1 收敛** `app/schemas.py`：普查确认无生产客户端仍发旧名 `question`/`thread_id`（deepagents `run-all.py` 调 adapter `/query` 已用标准名 `query`），**彻底移除** `AliasChoices` 双写兼容，入站契约收敛为纯标准名 `query`/`session_id`；清理未使用 `AliasChoices` import。`tests/test_api_smoke.py`、`agent-core/tests/test_guardrails.py` 示例字段名同步改 `query`。内部 `AgentState.question` 为 graph state 字段，与入站契约无关，保持不动。
- **文档一致性** `docs/architecture-improvement-plan.md`：§6.1 TB-1/TB-2 标注为「已落地（桥接）」；§6.2 U-1 标注「已闭环」；优化 A/B 标题回升「✅ 已落地」；#11 勘误回填。

## eval golden 已增至 15 条（2026-09-22）

> eval golden 集已增至 **15 条**（原 12 条）。上方历史条目中的 "eval 12/12" 为当时事实记录，按历史保留不改。


