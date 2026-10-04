# 测试实跑最佳操作手册（testing playbook）

> 来源：2026-09-28 `feat/isolation-hardening` 分支深度盘点 + 本地/远程真实环境实跑的完整沉淀。
> 目标：**又快又准**——用最小成本闭合测试盲区，结论只基于实跑证据。
> 对应长期记忆条目：分层实跑流程（task_experience）、Linux 容器最小配方（project_build_configuration）、psycopg 审计脚本缺陷范式（common_pitfalls_experience）、Windows 远程 SSH 范式（tool_experience）。

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
| 2 | **快速门禁**：`py_compile` + `ruff` + `lint_architecture.py` + `check_doc_sync.py`（docsync 自 2026-10-04 二批起以 `git ls-files` 为判定基准，路径存在性类问题**本机即可复现**；其余仍以本机 FS/环境为依据的校验正式证据按 §2.4 在干净检出上取） | 秒级，先行拦截 |
| 3 | **最窄子集**：`uv run pytest <改动目录>/tests -q`；迭代用 `--lf`/`--ff`，收窄用 `-k`/`-m` | 十秒~分钟 |
| 4 | **环境盲区补跑**：本机跑不了的（如 `tests/ha` 真实 PG，Windows 被 conftest 以 `sys.platform=="win32"` 硬跳过）在 Linux 容器/远程机实跑 | 视环境 |
| 5 | **CI 等价全量**：`make test` 9 session + eval + `uv lock --check` 收口 | 十分钟级 |
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
3. **别凭记忆断 skip 与 fixture 的先后**：实测探针（本机 `.codeartsdoer/temp/fixture_skip_probe/`，一个抛错的 autouse fixture + 一条 `skipif` 用例；一次性定性证据，**结论已在此句，脚本未入库**）得 `1 skipped, 2 errors` ⇒ **`skipif` 判定早于 fixture，被 skip 的条目根本不执行 fixture**。推论对定性至关重要：SDK 不在场形态下该文件最多只能报 9 errors，**15 errors 这一签名只在真 SDK 在场时可能存在** ⇒ CI（`make install` 后跑 ks，SDK 不在场）报绿**不构成对该线索的排除**，它跑的是另一种形态。用「CI 也绿」当排除证据前，必须先确认 CI 的形态与现场一致。


### 2.4 存在性类校验的「绿」必须在干净检出上取（2026-10-04 实踩，第十条假阳性）

`check_doc_sync.py` 这类门禁拿**本机文件系统**做存在性基准，而工作区里有一堆 gitignored 的脏目录
（`.codeartsdoer/`、`.venv/`、`.pytest_cache/`、`output/`…）。文档里引用一个**只在本机存在**的目录时，
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
同理适用于**任何**以仓内路径存在性为依据的校验（`lint_architecture.py` 的全仓扫描、`uv lock --check` 等）：
它们的本地绿都默认工作区无脏目录，而本仓不满足该默认。

**2026-10-04 二批：该门的判定基准已改，取证姿势不变但结论更强**。`check_doc_sync.py` 的存在性判定从
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
