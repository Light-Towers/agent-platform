# 测试实跑最佳操作手册（testing playbook）

> 来源：2026-09-28 `feat/isolation-hardening` 分支深度盘点 + 本地/远程真实环境实跑的完整沉淀。
> 目标：**又快又准**——用最小成本闭合测试盲区，结论只基于实跑证据。
> 对应长期记忆条目：分层实跑流程（task_experience）、Linux 容器最小配方（project_build_configuration）、psycopg 审计脚本缺陷范式（common_pitfalls_experience）、Windows 远程 SSH 范式（tool_experience）。
> 本手册管**怎么跑**；跑完之后"这条结论要怎么写才可核对"（五个必填字段、完成强度分档、新门禁的非空转反证表）见 `docs/operations/evidence-format.md`。两份配套用，别只引其中一份。

## 1. 测试目标与红线

**目标**
- 能本地验证的本地验证；本地受限（OS 硬跳过 / 缺真实外部系统）的，用真实 Linux/Docker 环境实跑补齐，**不得因本机跳过就声称已验证**。
- 每次实跑分析卡点并优化流程，让下次更快。

**红线**（与 AGENTS.md 一致）
- 禁止删用例 / 收窄断言 / 放宽前置条件凑绿。
- 失败先复跑区分「环境 flake」与「真实缺陷」，真实缺陷修产品代码到契约要求。

## 2. 分层执行流程（按成本从低到高）

| 步骤 | 动作 | 耗时量级 |
|---|---|---|
| 1 | **缺口盘点先行**：列出"未实跑项"（仅 mock 覆盖、本机硬跳过、需真实 DB 的脚本），它们才是验证重点 | 分钟级 |
| 2 | **快速门禁**：`py_compile` + `ruff` + `scripts/lint_architecture.py` + `scripts/check_doc_sync.py`（docsync 自 2026-10-04 二批起以 `git ls-files` 为判定基准，路径存在性类问题**本机即可复现**；其余仍以本机 FS/环境为依据的校验正式证据按 §2.4 在干净检出上取） | 秒级，先行拦截 |
| 3 | **最窄子集**：`uv run pytest <改动目录>/tests -q`；迭代用 `--lf`/`--ff`，收窄用 `-k`/`-m` | 十秒~分钟 |
| 4 | **环境盲区补跑**：本机跑不了的（如 `tests/ha` 真实 PG，Windows 被 conftest 以 `sys.platform=="win32"` 硬跳过）在 Linux 容器/远程机实跑 | 视环境 |
| 5 | **CI 等价全量**：`make test` 9 个标准 session + 1 个 `--extra otel` session（`Makefile:54-64`，别只数前 9 行）+ eval + `uv lock --check` 收口 | 十分钟级 |
| 6 | **失败定性复跑**：单跑复验 1-2 次；不可复现的计时类失败记为环境 flake 并如实汇报，不改代码 | 分钟 |
| 7 | **报告**：按"门禁项 / 命令 / 结果"分层表格输出，明确区分 passed / skip / 未跑 | — |
| 8 | **合入后主干复验**（判据 6 形态）：`uv run --no-sync python scripts/evidence/verify_main_tip.py --merge-sha <merge sha> --merged-at <gh 的 mergedAt> --baseline-max-number <基线>` ⇒ 七项 `[A]`–`[G]` 全 fail-closed。**PR 绿 ≠ 主干绿**，不得拿 PR checks 代替本步 | 分钟 |

**长任务执行方式**：后台化 + 输出落盘（bind-mount / `Tee-Object`）+ 轮询读取，抵御终端/SSH 通道断开；**读**时只看汇总行（`Select-Object -Last N`），但**写**时必须先把完整输出落盘——否则一次性红无从定性（见 §2.1）。共享 shell 若卡在续行提示符 `>>`，命令会**静默不执行**——以"预期产物文件是否生成"作为核实手段。**PowerShell 的 `>` / `Out-File` 默认写 UTF-16 LE**：拿它落盘的产物直接用 utf-8 读会得到夹 NUL 的文本（`print` 肉眼正常而正则/计数全 0）⇒ 读之前先 `uv run --no-sync python scripts/evidence/normalize_dump.py <dump>` 转码。

### 2.1 包装脚本的两条纪律（2026-10-03 实跑教训）

1. **完整输出先落盘，汇总只是它的衍生物**。批量脚本里 `$out = cmd; $out | Select -Last 3` 这种写法会在内存里丢弃前文：一旦某 session 报 `15 errors`（ERROR = fixture 装配阶段，详情只在 traceback 里），现场就永久丢了，只剩"复跑 5 次均绿"这种无法定性的陈述。正确形状：`cmd > log 2>&1` 后再从 `log` 取尾行（或 `Tee-Object -FilePath`），并给 pytest 加 `-rf --tb=short` 以便失败项带名字与原因。
2. **计数必须附带「在哪个 sha 上跑的」**。同一批测试在「中间工作态」与「commit 后的树」上 passed/skipped 常不同（新用例逐次落盘、skip↔pass 翻转都算），凭记忆写进账面的旧数字会被后人当真理。⇒ 任何「全量已绿」的声称后面要能回答：此数字对应哪个 commit？是否就是待 push 的那个 tip？

### 2.2 计数还必须附「extras / venv 形态」——同一 sha 合法存在两套数字（2026-10-03 实取）

§2.1 第 2 条只说「附 sha」并不充分：本仓 venv 由 uv 就地精确同步，**extras 状态会随命令序列翻动**，同一 commit 同一目录能跑出两种「全绿」计数。

实取证据（Windows 本机 `.venv`）：

| 动作 | 实测输出 | 对 ks session 的后果 |
|---|---|---|
| `uv sync --dry-run --all-packages --extra dev` | `Would uninstall 10 packages`，逐条为 `opentelemetry-*`（sdk / exporter-otlp / proto / semantic-conventions，仅 `opentelemetry-api` 留存） | —— |
| `uv sync --all-packages --extra dev`（= `make install`） | 真的卸载，`uv pip list` 只剩 `opentelemetry-api` | `396 passed, 13 skipped` |
| `uv run --extra otel pytest tests/observability`（Makefile session 10） | `Installed 8 packages` | `402 passed, 7 skipped` |

差的 6 条正是 `applications/knowledge-service/tests/unit/test_tracing.py` 里 `@requires_sdk` 守卫的用例（`15 passed` ↔ `9 passed + 6 skipped`），skip 数随之 `7 ↔ 13`。**这两个数字都是真的**，把它们当成「计数漂移」是账面噪声的一半来源（TODO §5 已登记项）。⇒ 声称「某 session 全绿」时，除 sha 外还要说清 extras 形态（一句话即可：`SDK 在场` / `make install 后默认形态`）。

**纪律**
1. 诊断性复跑（为定性一次红而反复跑同一 session）一律 `uv run --no-sync pytest …`：不碰 venv，保证各轮可比。
2. 改依赖后显式 `uv sync --all-packages --extra dev [--extra otel]`，并在账面记录该形态。
3. **绝不与正在运行的 pytest 批量并发执行 `uv sync`**：uv 会就地删装包文件，已启动的进程在后续 import 时会看到消失的模块——这正是「一次性、不可复现的装配期 error」的典型来源。

### 2.3 用计数算术把「一次性红」收窄到唯一站点（ks 15 errors 实操范式）

拿到 `387 passed / 7 skipped / 15 errors` 这类只报数字不报现场的旧账时，按此三步，不必猜测：

1. **对齐总数**：`--collect-only -q` 实取 collected（ks = 409）。若 `passed + skipped + errors == collected` 与全绿形态的 `passed + skipped` 相等 ⇒ 集合没变，失败形态是「同一集合里恰好 N 条在 **setup 阶段 error**（不是 fail）」。
2. **按文件分组数用例**：找「恰好 N 条」的文件（ks 全 suite 中唯一 15 条的文件 = `tests/unit/test_tracing.py`），再看该文件是否共用同一个 autouse fixture（ks 为 `_reset_tracing`，前后各调一次 `tracing._reset_for_tests()`）——autouse fixture 抛错即精确复现「N errors + 其余全过 + skip 数不变」的现场签名。
3. **别凭记忆断 skip 与 fixture 的先后**：实测探针（本机 .codeartsdoer/temp/fixture_skip_probe/，一个抛错的 autouse fixture + 一条 `skipif` 用例；一次性定性证据，**结论已在此句，脚本未入库**）得 `1 skipped, 2 errors` ⇒ **`skipif` 判定早于 fixture，被 skip 的条目根本不执行 fixture**。推论对定性至关重要：SDK 不在场形态下该文件最多只能报 9 errors，**15 errors 这一签名只在真 SDK 在场时可能存在** ⇒ CI（`make install` 后跑 ks，SDK 不在场）报绿**不构成对该线索的排除**，它跑的是另一种形态。用「CI 也绿」当排除证据前，必须先确认 CI 的形态与现场一致。


### 2.4 存在性类校验的「绿」必须在干净检出上取（2026-10-04 实踩，第十条假阳性）

`scripts/check_doc_sync.py` 这类门禁拿**本机文件系统**做存在性基准，而工作区里有一堆 gitignored 的脏目录
（.codeartsdoer/、.venv/、.pytest_cache/、output/…）。文档里引用一个**只在本机存在**的目录时，
本机 rc=0 而 CI 红（本批实踩：`ARCHITECTURE.md` 写了 .codeartsdoer/temp 的目录形，PR #65 的 `ci` 在
`Doc sync check` 步报 `路径不存在`，而本地同命令一直绿）。⇒ **本机绿不构成证据**。

固定取证据姿势（不靠猜 CI 行为，直接构造同构检出）：

```powershell
git worktree add --detach $env:TEMP\wt<sha> <sha>     # 只落地 tracked 文件 ⇒ 与 actions/checkout 同构
Push-Location $env:TEMP\wt<sha>; <venv>\Scripts\python.exe scripts/check_doc_sync.py; $LASTEXITCODE; Pop-Location
git worktree remove --force $env:TEMP\wt<sha>         # 验完回收，`git worktree list` 应只剩主工作区
```

两条约束：① **双向都要实取**——旧内容在干净树上能复现出与 CI 逐字相同的红（排除「CI 环境问题」），新内容在同一
树上转绿（排除「改得不够」）；② 把改动文件拷进干净树时用 `Copy-Item`（按字节拷，不被编辑器改写行尾）。
同理适用于**任何**以仓内路径存在性为依据的校验（`scripts/lint_architecture.py` 的全仓扫描、`uv lock --check` 等）：
它们的本地绿都默认工作区无脏目录，而本仓不满足该默认。

**2026-10-04 二批：该门的判定基准已改，取证姿势不变但结论更强**。`scripts/check_doc_sync.py` 的存在性判定从
「本机 FS 有没有」改为「版本控制清单（`git ls-files`）里有没有」⇒ 本机脏工作树现在**与 CI 同样会红**。
差分实取（同一脏工作树 + 同一探针行）：旧实现 rc=0 放行，新实现 rc=1 并报
「路径未纳入版本控制 '.codeartsdoer/temp/'（本机存在但未入库：CI / 新克隆上不存在）」；
取不到清单时 **fail-closed** 报红，绝不退回 `Path.exists()`，也不提供 `--skip-git` 类旁路开关。
⇒ 干净检出复验**不再是这一门的必需项**，但**保留为通用纪律**：任何仍以本机 FS 或本机环境为依据的
校验（目录扫描、`uv lock --check`、需要外部服务/环境变量的分支）都可能本地绿 / CI 红，
「旧内容能复现红 + 新内容同树转绿」的双向实取仍是唯一能给结论的取法。
本批仍按方案 §5 判据 6 实取了两个 sha 的干净树（`git worktree add --detach`，实取 `tracked files=1073`、
`.codeartsdoer` 与 `.venv` 均不在场）：本批 tip 上新实现 rc=0 且用例 35 passed，主干 `3546190` 上旧实现
rc=0 且 17 passed（基线对照）⇒ 「绿」是在 CI 同构树上取到的，不依赖本机脏工作树。
方案与验收：`docs/plans/plan-doc-sync-tracked-scope-2026-10-04.md`。

### 2.5 「0 collected」可能是整模块跳过，不是「没有用例」（2026-10-27 实取）

`packages/agent-runtime/tests/test_cache_contract.py`（真 Valkey 契约：L1/L2 命中、阈值拒绝、租户/scope/KB/灰度隔离、空租户 fail-closed、写侧 PII 门禁）在 Valkey 不可达时不会显示为 skip，而是**整模块收集为空**——文件里用的是 `pytest.skip(..., allow_module_level=True)`（`:56-60`）：

```bash
uv run pytest packages/agent-runtime/tests/test_cache_contract.py --collect-only -q
# => no tests collected in 1.16s（2026-10-27 本机实测；同机 test_valkey_backend_wire.py 可收集 86 条）
```

⇒ 判「这组用例不存在 / 被删了」之前，先看文件里有没有 `allow_module_level=True`；`no tests collected` 不进任何 passed/skipped 分母，**既不能写成「本机全绿」，也不能据此判「无覆盖」**（前者假绿、后者误报缺口）。条数要用 AST 点算，或按 §2 第 4 步到 Linux 容器/测试机实跑。本机无 docker/podman，`wsl.exe -l -q` 虽 rc=0 但无发行版输出（2026-10-27 复核；`tests/ha` 另有 `sys.platform=="win32"` 硬跳过），跳过提示里的 `docker compose up -d valkey` 在本机不可执行；`CACHE_CONTRACT_REQUIRED=1` 能让它收进 19 条，但本机没有 Valkey，跑起来必红——那是 CI 的 fail-closed 判据，不是本地通过路径。同目录 `test_valkey_backend_wire.py`（86 条）用进程内 `_FakeClient`，证明的是协议形状，不能代替真 Valkey 的 L2 行为。

### 2.6 「漏 await」这一族**两条自动化路都不可用**——别再试（2026-10-27 实测）

历史缺陷（`memory_backend` 漏 await ⇒ 类型化记忆恒空，被 4 处 monkeypatch 盖住）看起来很像能自动拦，两条路都实跑过，都拦不住：

**路 A：静态扫「裸调用 async def」** → 515 文件 / 825 个 `async def`，主判据 21 条候选，**21/21 是假阳性**。根因是 AST 只有名字没有类型：`task.cancel()`、`cursor.execute(sql)`、`client.flush(...)`、`random.seed(42)`、`self._guard._sem.release()` 这些**第三方同步方法**与仓内同名 `async def`（`planner/protocol.py:570 async def cancel`）撞名。按名字匹配不构成证据； receiver 类型静态推不出来，除非只认 `self.<本类定义的 async 方法>` 这种可解析形状（覆盖面因此极窄）。复现方法：遍历 applications/ 与 packages/（跳过 tests/ 与 eval/），收集全仓 `async def` 名单，再把 AST 里 `ast.Expr(value=ast.Call)` 的裸调用按函数名对上那份名单——就得到上面那 21 条。

**路 B：把解释器的 `coroutine 'X' was never awaited` 升成 CI 红** → **不可行**。先拿正控自证：

```bash
printf 'import gc
async def _noop():
    return 1
def test_probe():
    _noop()
    gc.collect()
' > tests/test_zz_probe.py
uv run pytest tests/test_zz_probe.py -q -W "error:coroutine .* was never awaited:RuntimeWarning"
# 实测：1 passed, 1 warning（2026-10-27 本机）⇒ 升级判据不成立，门禁是空的
rm tests/test_zz_probe.py
```

原因：警告在协程对象被 GC 回收时发出，那已不在用例执行上下文里，pytest 归不到用例、`-W error` 也就不会让它红。**所以「9 个 session 加了这个 `-W` 之后 0 命中」不能当作「本仓没有漏 await」的证据**——它只证明这条过滤条件不产生任何判定（与 §3.5 变异战役开工前「先跑引擎自带探针自证能杀」是同一条规矩：判据不自证能红，就等于没有判据）。

⇒ 这一族目前只有两条真路：① 用例侧断言（如 `packages/agent-runtime/tests` 对记忆写读端到端断言"类型化记忆非空"，漏 await 时用例自然拿不到数据）；② 评审时盯 `async def` 调用点的 `await`。要新增自动化拦法，先写正控证明"注入漏 await 会让它红"，再谈接线。

### 2.7 长跑不要经 `-File` 包装器；墙钟不得跨调用形状比较（2026-10-30 实取）

同一条 `uv run pytest -q -m "not requires_pg"`、同一 rev `27fb1e41`、同一组计数（1486/10/29），两种起法差 **12 倍**：

| 起法 | 读数 |
|---|---|
| `powershell -NoProfile -File <一次性包装器脚本>`（该脚本**不入库**，只是个逐条跑 session 的 for 循环） | **1908.73s**（含两例 CPU 停增的冻死：每 20–25s 采样 Δ=0.0s、TCP **0 条**、无子进程、共 3 线程） |
| 直接在工具 shell 里起（同样后台转发） | **154.91s** |

机制**未归因**（实例 4 vs 3，样本小）。形状上像输出/控制台背压——唯一不受影响的包装器实例是输出量最小的那个（28 项只打 1 行），但本轮没证它。
我此前下过“后台起必冻”的结论，被后面的读数推翻了：变量不是前/后台，是**有没有经过这层包装器**。

⇒ 三条操作约定：
1. **长跑 session 直接起命令**（可以后台转发），不要经 `powershell -File <脚本>` 这层包装器；要批量就逐条直接起，不要拿包装器跑全量后拿它的耗时做排期依据。
2. **墙钟耗时不得跨调用形状比较**；两种形状之间只能引用 rc 与计数。否则会把包装器开销读成“套件真慢”：台账 P3「`tests/governance` 超 9 分钟」就是这样被误登记、又这样被单跑推掉的（`tests/governance -q` = **464 passed / 1 skipped in 102.58s**，与同日上午 102.86s 同值）。
3. **取阴性（“0 命中 / 0 条”）必须单独跑、并看 rc**：本轮一条 `git grep` 夹在串命令里，屏幕没回显命中行就被当成零命中；单独复跑逐字一致的命令 rc=**0**、**40 行命中**。同族坑见本节引言的“`Select-Object -Last N` 只适合读不适合写”与“`>>` 续行静默不执行”。

取证：`docs/operations/evidence/2026-10-30-full-session-sweep/readings.md` §4（形状对照 + 实例表）与 §6（未归因声明）。

## 3. 本仓特定配方

### 3.1 Linux 容器跑 tests/ha + identity（最小安装）

```bash
# 依赖：切勿 --all-packages（会拉全部 6 个 application；eval extra 含 flashrag
# git+https 构建，需 git 且极慢，是最大的耗时陷阱）
uv sync --extra dev                # 仅 pytest / pytest-asyncio / ruff

# tests/ha 需要 pgvector 真实 PG（规格同 docker-compose.ha.yml）：
#   pgvector/pgvector:pg16 → 127.0.0.1:5433，库/用户见 tests/ha/conftest.py 默认 DSN
#   测试容器用 --network host 复用同机 PG
uv run pytest tests/ha -q          # 预期 27 passed

# identity 套件（ADR-0007 RS256/HMAC 真实密码学）：PyJWT 在 agent-runtime
# 是 optional extra `identity`，不在默认依赖，须补装
uv pip install PyJWT cryptography
uv run pytest <identity 测试目录> -q   # 预期 40 passed
```

### 3.2 psycopg 只读审计/运维脚本三原则（真实库教训）

`scripts/audit_tenant_access.py` 连真实 PG 暴露的三个缺陷，mock 单测永远发现不了：

1. **显式 autocommit**：psycopg v3 默认 `autocommit=False`，单条 SQL 失败使事务进入 aborted 态，后续查询级联报 `current transaction is aborted`——"逐项 try/except 互不中断"成假象。只读扫描脚本建连后必须 `conn.autocommit = True; conn.read_only = True`。
2. **不硬编码 schema 列名**：按 `information_schema.columns` 做防御性列探测，缺列**降级**（如本表无命中计数列则仅按条目数统计并在报告注明）而非抛错。
3. **渲染层防御性取值**：报告渲染用 `sec.get('status', 'n/a')`，任何单项结构缺键不得导致整份报告不落盘。

> 结论性教训：凡连真实外部系统（DB 等）的脚本，**必须在真实环境至少跑一次**才算验证。

### 3.3 Windows → 远程 Linux 实跑通道（Posh-SSH 范式）

本机 OpenSSH 需交互输密、无 sshpass 时：
- `Install-Module Posh-SSH`（先 bootstrap NuGet provider），纯 PowerShell 非交互密码 SSH；
- 长任务不在 SSH 前台跑：`docker run -d` + bind-mount 日志文件，宿主 `tail` 轮询；
- PowerShell 引号陷阱：单引号内 `\"` 会被当串结束、`$?` 是本机自动变量而非远端回传、多行 here-string 易触发终端守卫——复杂命令拆单行或先落盘脚本再 `-File` 执行；
- 端口测绘用 `System.Net.Sockets.TcpClient.ConnectAsync(...).Wait(1500)`，勿用 `Test-NetConnection`（unreachable 端口约 21s/个）。

### 3.4 本机零基建起真 PostgreSQL（2026-10-24 实测，Windows 无 docker/无 psql）

**先记住这条推翻的旧前提**：本机曾按「Windows 开发机没有 PG ⇒ `requires_pg` 只能等环境」处理，
实测口径是——`pgserver`（PyPI，约 12MB，有 `cp311-win_amd64` wheel）**自带 PostgreSQL 16.2
且内置 pgvector**，免 docker、免管理员、免服务注册：

```bash
# 一次性探针（不进依赖树：--no-sync 且 --with 只装进临时环境）
uv run --no-sync --with pgserver python your_probe.py
```

```python
import asyncio, pgserver, psycopg
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # ← 少了这条 psycopg 异步必炸
srv = pgserver.get_server(r"D:\Study\github\agent-platform\.pgserver-probe")  # 目录已 gitignored
with psycopg.connect(srv.get_uri()) as c:  # 建 scratch 库、跑迁移、断言
    ...
```

五条实测要点：
1. **`WindowsSelectorEventLoopPolicy` 是必需项，不是可选项**。`tests/ha/conftest.py` 在 win32
   直接 skip 的理由就是 Proactor 事件循环——它 skip 的是**事件循环**，从来不是"拿不到 PG"。
   换 Selector 后 `agent_runtime.pool_factory.create_pool` 在本机直连 pgserver 正常跑。
2. **别把它加进 `pyproject`**：探针用 `--with` 临时装，跑完即弃，避免把开发期工具固化成依赖面。
3. **每次现起现删 scratch 库**（`DROP DATABASE IF EXISTS` + `CREATE DATABASE`），别复用带残留的库——
   复用会让"迁移幂等"的结论被上一轮状态污染。
4. **它的价值在能证伪 L1**：2026-10-24 就是用这条通道实跑证伪/证实了三个阻塞项
   （42P01 连带回滚整链、23502 NULL 进 NOT NULL、42P10 ON CONFLICT 目标键不存在），
   而这些在单测里全绿。台账见 `docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md` §9.16。
5. **也能验"配置真的接上了"**：2026-10-25 用同通道验 issue #146——
   设 `AGENT_PLATFORM_DATABASE_URL` 后联邦 `init_pool()` 返回非 None、迁移到 v15、
   `memories.embedding` 为 `vector(512)`、`remember_fact` → `recall_typed` 命中刚写入的事实；
   修复前同一调用恒返回 None（配了 DSN 等于没配）。该结论已固化为
   `applications/agent_federation/tests/test_db_integration.py`：缺 `AGENT_PLATFORM_PG_URL`
   即 skip；本机先起 pgserver 再把其 URI 设进该变量即可跑该文件（接线回归会红，不会 skip）。

**仍要用 Linux CI/126 的场景**：需要 pgvector 之外的扩展、或要验真实并发/故障转移时，
本机进程内 PG 不够（单机单连接池），照 §3.1 容器与 `.github/workflows/ha.yml` 的 PG service 走。

### 3.5 变异战役：命令、耗时、读数定性口径（2026-10-26 首跑）

两件仪表，**别混**（AGENTS.md「逻辑测试靠变异杀死率」的落地件）：

- `make mutation-cache` = **门禁**：手挑一批性质（条数以脚本 `MUTANTS` 为准，散文里不抄数）+ 声明式存活集合 `ENGINE_OWNED`，判据是"存活集合
  等于声明"，可拦红绿。漂移只有两种解释（用例退化 / 用例获得了假层不具备的解释能力），都要人定性。
- `make mutation` = **战役**：AST 算子自动展开，**分母来自代码**——手挑清单的盲区恰恰是"谁挑的、挑了什么"。

自定义目标与套件的完整命令（`{python}` 由引擎换成当前解释器，省掉 uv 启动开销）：

```bash
uv run python -u scripts/mutation_engine.py \
    --target packages/agent-runtime/agent_runtime/cache \
    --timeout 120 \
    --command "{python} -m pytest packages/agent-runtime/tests/test_valkey_backend_wire.py \
        packages/agent-runtime/tests/test_cache_config.py tests/test_bench_cache_write_budget.py \
        -q -x --no-header -p no:cacheprovider" \
    --report .tmp-scratch/mutation-report.json
```

**战役期间工作区是"半改写"状态**，三条纪律（2026-10-26 首跑实测，读数与定性见 ADR-0013 §11 第 37–41 行）：

1. **别在战役跑着时编辑或提交被检目录**——引擎就地改写源文件，而变异体是 `ast.unparse` 出来的：注释全无、行号漂移。
   本仓是共享工作区，并行会话会把这种半成品直接提交走。
2. **进程被硬杀时用快照还原**：开跑前引擎把原始字节抄一份到 `.tmp-scratch/mutation-snap/<target>/` 并打印 sha256；
   正常退出 / Ctrl-C / 信号走 `atexit` + handler 还原，`Stop-Process` 这类硬杀谁都不跑。本轮实测：中途硬杀确实
   留下了一个无注释的 `config.py`，按字节 `cp` 快照回去 + 核 sha256 即可。
3. **`--timeout`（默认 180s）兜住单刀挂死**：超时**计为被杀**，但报告里标 `timed_out=true`——"跑挂"不等于"暴露缺陷"，
   分诊时单独一档看。要边跑边看读数就加 `-u` 启动：stdout 重定向到文件是块缓冲，进程活着而日志 0 字节是常态。
4. **只复跑改动过的那一个文件用 `--only <文件子串>`**：本轮实测 `--only valkey_backend` = 226 刀 ≈ 8 分钟，整目录 341 刀 ≈ 22 分钟。
   但**两次战役之间只有 digest（变异后源码哈希）能逐刀对齐**——实现一改，分母就会漂（补 4 个计数器键就让 `disabled_backend.py`
   从 12 刀变 20 刀），所以"几刀翻红、几刀倒退"必须由 digest 差得出，不能拿两轮的条数相减。
5. **战役跑着时也不要改用例**（不只是别改被检目录）：引擎每下一刀都重新起一次 pytest，基线自检只在开工时跑一次。
   中途改用例会**污染后半轮**——新加的用例让后面的刀更容易记成"被杀"，而它没参与开工时那次基线；
   改坏了更糟：套件一红，之后每一刀都被判"被杀"，杀死率会变成纯噪声。⇒ 一轮战役是一个不可变测量，
   要改用例就等它跑完再开新一轮（读数按 digest 对齐，两轮之间可逐刀比较）。

**开工前的三道自检**（任一不过就中止，不产出杀死率）：基线套件必须绿；探针模块（`value > 3` + 四条边界
断言）展开的变异必须**全被杀**——引擎整条是空的也会报出"杀死率 40%"，那会被误读成套件弱；
"只 unparse、不变异"的往返对照必须绿，否则红可能是仪表造的。结束时按 sha256 核对还原（异常路径也还原）。

耗时口径：每个变异重跑一遍套件。被杀通常 ~0.6s（`-x` 首个失败即停），存活要等全套跑完 ~3.5s，
所以**一个文件几百刀 = 十几到几十分钟**，别挂进 PR 门禁；改动被测模块后或定期跑。

存活体（survived）三类定性，都要人分，**不许把"套件仍绿"当"没问题"**：

| 类别 | 怎么认 | 处置 |
|---|---|---|
| 等价/噪声 | 改完语义不变（如日志截断长度 `200→201`、平台分支 `sys.byteorder != 'little'`） | 记一句理由，不补用例 |
| 引擎独占 | 判据依赖被调用方的解释规则（TAG 过滤串、负缓存对后续读的影响），假客户端层看不懂 | 归到真机契约层，写进 `ENGINE_OWNED` 并留契约用例（`make test-cache-contract`） |
| 真缺口 | 该分支的行为**没有任何断言**（例：`disabled_backend` 的 stats 字典里 `0→±1` 全存活） | 补用例，然后复跑确认这一刀变 KILLED |

### 3.6 126 上补跑两条真依赖 session（2026-10-27 实测配方，可直接抄）

当日实况（先读再动手，别按本机假设）：126 有 `ap-test-base:2`（Python 3.11.16，**系统解释器无 pytest**）、`pgvector/pgvector:pg16` 以容器 `ap-iso-pg` 跑在 `127.0.0.1:5433`、`valkey/valkey-bundle:9.1.2` 镜像在库；`/opt/agent-platform/.venv` 依赖树完整但**不含 `valkey` 客户端**。宿主 `0.0.0.0:6379` 是 apt 装的 `/usr/bin/redis-server`——**不是 Valkey、没有 search 模块**，拿它跑契约用例会得到与代码无关的红。

```bash
# 1) 全套补跑只能走 git bundle + clone（AGENTS.md 第 1 条的既定通道），两个坑一起避开：
#    - tar 工作区带 CRLF ⇒ "migration checksum mismatch for v1 ('baseline')" ⇒ 真 PG 用例整片 skip
#    - git archive / tar 出来的副本没有 .git ⇒ 一切以 git ls-files 为存在性基准的门禁
#      报 "仓内路径清单不可用 ⇒ 门禁 fail-closed"（本轮实测：根套件因此多 6 条红，
#      断言原文带 120 项）。那 6 条红是**交付形状**造成的，门禁红得对，不许为它放宽
git bundle create full.bundle <分支名>          # 13.7MB 量级，比 tar 全树还小
scp full.bundle <126>:/tmp/ && ssh <126> 'git clone -q -b <分支名> /tmp/full.bundle /tmp/qoder-git/tree'
#    只跑 tests/ 之外、且不读 git 清单的 session 时 git archive 够用；全套不要用。
#    clone 完先自证：git rev-parse --short HEAD 与 git ls-files | wc -l 都要有数

# 2) tests/ha 对真 pgvector：用新建库，别复用 ap-iso 的旧 schema
#    （它的 v6 在 6cb1c639 被就地改过——legacy DB 崩的修复——checksum 必与 HEAD 不符）
ssh <126> 'docker exec ap-iso-pg psql -U agent -d postgres -c "CREATE DATABASE agent_platform_ha_<date>"'
ssh <126> 'docker run --rm --network host -v /tmp/envrun-<date>:/srv/agent-platform \
    -v /opt/agent-platform/.venv:/srv/agent-platform/.venv -w /srv/agent-platform \
    -e AGENT_PLATFORM_PG_URL=postgresql://agent:agent_platform_dev@localhost:5433/agent_platform_ha_<date> \
    ap-test-base:2 /srv/agent-platform/.venv/bin/python -m pytest tests/ha -q'
#    实测 29 passed in 12.40s（本机同套件只有 1 passed / 28 skipped；.venv 的 bin/python
#    在宿主是断链，进容器解析到 /usr/local/bin/python3 即可直接用，别重装依赖）

# 3) 缓存契约对真 Valkey：起一个用完即删的 bundle，端口避开 6379 上那个 redis
ssh <126> 'docker run -d --name qoder-valkey-<date> --network host valkey/valkey-bundle:9.1.2 \
    valkey-server --port 6380 --save "" --appendonly no'
#    客户端 126 全 estate 都没有 ⇒ 从本机 venv 原样搬（不装、不联网）：
#    tar czf valkeydep.tar.gz -C .venv/Lib/site-packages valkey valkey-6.2.0.dist-info
ssh <126> 'docker run --rm --network host -v /tmp/envrun-<date>:/srv/agent-platform \
    -v /opt/agent-platform/.venv:/srv/agent-platform/.venv -v /tmp/valkeydep-<date>:/extra:ro \
    -w /srv/agent-platform -e PYTHONPATH=/extra -e VALKEY_URL=redis://127.0.0.1:6380/0 \
    -e CACHE_CONTRACT_REQUIRED=1 ap-test-base:2 /srv/agent-platform/.venv/bin/python \
    -m pytest packages/agent-runtime/tests/test_cache_contract.py -q'
#    实测 19 passed in 3.73s；起服务后先 `valkey-cli -p 6380 module list` 确认 search 已加载
#    正控，否则"19 passed"可能是 L2 被静默跳过的假绿。`make test-cache-contract` 是同一判据
#    的 CI/本机形状，126 宿主无 uv ⇒ 只能抄上面的等价容器命令。
```

顺手查出来的**现网事实**（不是本轮改动引入，但决定语义缓存在现网能不能开）：跑着的 Pod `agent-platform-85794678c-vktrc`（`GIT_REV=6ac466af`）里 `import valkey` → ModuleNotFoundError，而 `valkey>=6.2.0` 是 `packages/agent-runtime/pyproject.toml:18` 的**硬依赖**；同 Pod 的 `CACHE_ENABLED` / `CACHE_BACKEND` / `VALKEY_URL` 三个 env 全为空。⇒ 现网既没注入缓存配置，镜像也没带客户端；只把 `CACHE_BACKEND` 改成 valkey 会在 `agent_runtime/cache/factory.py:34` 启动期 fail-closed（不静默降级，这一层设计是对的）。要启用必须先重建并分发镜像，属 D2 动作。

## 4. 已验证基线（2026-09-28 实跑快照）

| 范围 | 结果 |
|---|---|
| 远程真实 PG：`tests/ha` | 27 passed |
| 远程真实密码学：identity 套件 | 40 passed |
| 本地 CI 等价：根 session（`-m "not requires_pg"`） | 678 passed, 27 deselected |
| 本地：`tests/` 直跑 | 450 passed, 26 skipped |
| 本地：8 个子包 session | 全绿（agent-runtime 608×3 轮复跑稳定；首跑 8 failed 为冷启动环境 flake，不可复现） |
| 门禁：ruff / lint_architecture / check_doc_sync / eval / uv lock --check | 全过 |

## 5. 远程演练（k8s 集群取证复跑）

> 适用：Windows 本机 → 126（control-plane，构建机）→ 125/241（worker）的三机实跑。
> 工具面：§3.3 的 Posh-SSH 通道 + `deploy/k8s/scripts/` 六件套（用法/判据/退出码见其 README「可复跑取证」节）。
> 本节只记**操作守则**（本轮 16 个 scratch 脚本踩出来的坑，每条都有对应事故）：

1. **短命令 + 脚本承载复合逻辑**：sandbox/引号层对长复合命令（多条 scp+ssh 合并）会回显风暴且静默失败（曾现 scp 未落地而 RC=0）——复合逻辑一律落 `deploy/k8s/scripts/*.sh`，Windows 侧只发 `scp` + `bash xxx.sh` 两条短命令。
2. **行尾**：经 git checkout 到远端的脚本天然 LF（`.gitattributes` 强制 `*.sh eol=lf`）；scp 直传工作区文件则先 `sed -i 's/\r$//' *.sh` 再执行。
3. **落地验证不凭 RC**：每次同步/改动后远端 `grep` 关键字 / `md5sum` 比对确认内容真落地（126 假同步事故：本地改了 routes.py，镜像内仍是 426 行旧版）。
4. **PowerShell 假阳性定性套路**：stderr 触发 NativeCommandError 包幕（uv 的 "Resolved N packages" 即走 stderr）——一律 `cmd; echo RC=$LASTEXITCODE` 看真退出码，不看 Red 文本下结论；`Access is denied` 拦 uv 多为命令内含删除类动作被沙箱降级，拆开用安全工具（DeleteFile）单独做。
5. **验证对象绑定提交**：取证结论必须能说「镜像 rev == 待验 rev」：构建走 `build.sh <rev>`（rev 不匹配 exit 2 即中止），取证后 `verify.sh <rev>` 回查镜像内 GIT_REV；脏工作区构建须在证据块注明 dirty。
6. **共用机纪律**：三台是共用测试机——containerd 走隔离实例（sock=`/run/containerd-k8s/containerd.sock`，勿打裸 ctr）；port-forward 用 `portforward.sh`（先清旧再拉起，防占端口 HTTP=000）；演练结束清理（kubeadm reset）须用户二次确认。
