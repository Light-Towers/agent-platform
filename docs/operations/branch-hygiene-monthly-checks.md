# 分支月度体检（活文档，每月一节）

> 落地件：AGENTS.md《分支卫生》第 3 条「月度体检」。本文件**每月追加一节**，不重写历史节（历史节是时点快照，读数绑当时的 tip）。
> 判据不另立：死枝判据与「独有提交」测法沿用 `docs/operations/git-ref-cleanup-2026-10-04.md` §1（尤其 #2「base 必须取真实 base」与 #3 `git cherry -v`），本文只负责**按期跑 + 留可复核读数**。
> **纪律**：体检报告本身不执行删除。删除动作属另一回事，须逐条经用户点头；顺序是 **先 `git merge <该枝>`（内容不在当前线时会真合入）→ 再 `git branch -d`**。⚠ 本轮实跑查到一条会让 `-d` 行为出乎意料的规则：**分支带 upstream 时，`-d` 校的是“已合入 upstream”而不是“已合入 HEAD”**，两者可以同时成立而 `-d` 仍拒（原文：“…even though it is merged to HEAD”）。此时不是“判据不成立”，而是**判据要换一条**：另取 `is-ancestor <枝> HEAD` + `rev-list HEAD..<upstream>` 两条，均为 0/rc=0 则删 ref 不丢提交；按 AGENTS.md《分支卫生》#1，**只有已有 ADR/文档登记的确证退役结论时**才转 `-D`（无结论则停手，不许 `-D`）。

## 命令面（只读，任何时刻可原样复跑）

```powershell
# 1. 先取实际远端名。注意：本仓无 origin（是 company + 禁推的公开镜像 github-legacy）
git remote
#    ↑ 用 `git remote` 而不是 AGENTS.md 原文的 `git remote -v`：后者会打印内网 URL，
#      而本文是入库件（公开镜像门禁 lint_public_mirror 零容忍新公开内容）。远端名够用。

# 2. 远端 heads 计数（>2 报警）
git ls-remote --heads company

# 3. 本地逐条查独有内容（三件一起看，缺一会误判）
git for-each-ref --format='%(refname:short)' refs/heads
git cherry -v <base> <branch>                 # '+' 行数 = patch 层独有提交
git diff --name-only <base>...<branch>        # 非空即「唯一持有」，否决删除
git merge-base --is-ancestor <branch> <base>  # rc=0 ⇒ 该分支是 base 的祖先（最强的一条）

# 4. worktree 面（被占用的分支 `git branch -d` 会拒删，必须先知道）
git worktree list

# 5. remote-tracking 现态（区分「本地见过的」与「远端真实有的」）
git for-each-ref --format='%(refname:short) %(objectname:short)' refs/remotes
```

**两条读数陷阱**（本轮实测踩到，写死在这里）：
1. **base 异宗 ⇒ 量纲假象**：`company/main` 是一条**孤儿快照线**（tip 只有 2 个提交，`git merge-base company/main <工作线>` rc=1 ⇒ 无共同祖先）。拿它当 base，每条分支都会报出 600–1000 个「独有提交」，那是异宗造成的，**不是债**，也不构成死枝判据。⇒ 判「独有」必须先验 `merge-base` 存在。
2. **`ls-remote` 失败时 `refs/remotes/*` 不能当现态**：本轮 `github-legacy` 取不到（rc=128，网络层被阻），本地那 10 个 `github-legacy/*` ref（**9 条分支 + 1 条 HEAD 符号引用**，`git for-each-ref refs/remotes/github-legacy` 实取）只是上次 fetch 的**旧快照**。⇒ 报告里必须分成「实测」与「未取证」两栏，不得用旧快照冒充现态。

---

## 2026-10-29 节（首次跑本清单；读数绑 HEAD `896f966e`，分支 `feat/nl2sql-ttl-and-006-slim`）

### 1. 远端面（实测）

| 远端 | heads | 读数 |
|---|---|---|
| `company` | **1 条** | `refs/heads/main` @ `fe22794c`（提交信息自陈「2026-10-20 快照，源 on-disk tip 3e23b7b」，`rev-list --count` = 2 ⇒ 孤儿快照线，与本地历史不同宗） |
| `github-legacy` | **未取证** | `git ls-remote` rc=128（无法访问 github.com 该仓）⇒ 本轮拿不到现态；push URL 为禁用占位（设计如此，见 AGENTS.md《分支卫生》#4） |

**报警判定**：AGENTS.md #3 的报警条件是「远端 >2」⇒ `company` = 1 条**不报警**。但终态描述与现状不符（下一条），这是本轮体检真正的产出。

### 2. 拓扑偏差（需人拍板，D2，我不擅自动）

终态写的是「远端恒 2 分支：`main` + 唯一集成分支」。实测三点不符：

| # | 事实（可复核） | 为什么不是我能顺手修的 |
|---|---|---|
| ① | `company` 只有 `main`，**没有集成分支**；名为集成分支的 `fix/dependabot-security-int` 只活在本地，无 upstream | 补第 2 条 = 往远端推新分支（外部可见动作）；且要先定「集成分支是哪条」 |
| ② | `company/main` 是**异宗快照线**，与本地历史无共同祖先 ⇒ 它不是「能 PR 合回」的 main，而是周期性 squash 快照的载体 | 要么改流程（让 company 承接真实历史），要么改 AGENTS.md 那句终态描述以匹配「快照推送」模式。两者都是策略选择 |
| ③ | 本地 `main` @ `88515cab` 与当前工作线**互相领先**（main 有 6 个提交不在工作线，工作线有 339 个提交不在 main；`merge-base --is-ancestor main HEAD` rc=1） | 谁合进谁是 D2。本文件只报数 |

### 3. 本地分支逐条（9 条；base 取**当前工作线** `feat/nl2sql-ttl-and-006-slim`，缩写 HEAD）

| 分支 | cherry `+` vs HEAD | 独有文件 vs HEAD | 是 HEAD 祖先 | 分类 | 复审触发条件（AGENTS.md #2：没这条不许登记） |
|---|---|---|---|---|---|
| `feat/nl2sql-meta-build-recovery` | **0** | **0** | **是** | **已于 2026-10-29 退役删除**（本地；过程与判据见下方订正与 `docs/adr/0012-nl2sql-branch-consolidation.md` §4） | 已执行 ⇒ 本行转为历史；若发现某 commit 只在 `github-legacy` 那条上 ⇒ 从镜像侧 fetch 回来重立并推翻结论 |
| `company-snapshot` | 2 | 1（异宗，见陷阱 1） | 否 | **冗余本地副本**（tip == `refs/remotes/company/main`） | 只要 `refs/remotes/company/main` 仍在，本地这条即无唯一持有 ⇒ 可删；若哪天 `company` 远端那条快照被重写/删除，本条升为**唯一持有，禁删** |
| `fix/dependabot-security-int` | 2 | **6**（`pyproject.toml`、`uv.lock`、三处包 `pyproject.toml`、`plan-platform-tenant-workspace-identity-2026-10-18.md`） | 否 | **非死枝**：依赖安全批次的 lock 内容不在当前线里 | 出现「这 6 个文件的改动已进 main 或已进当前线」（`git diff --name-only HEAD...该分支` 归零）即复审 |
| `docs/dependabot-round4-2026-10-24` | 2 | 7 | 否 | 非死枝（vs 本地 `main` 是 `cherry+ 0`，已并入；vs 当前线仍独有） | 集成分支拓扑（②③）定了之后重算：若它内容全在那条唯一集成分支上即降为死枝 |
| `fix/dependabot-pillow-13-2026-10-24` | 3 | 7 | 否 | 非死枝（同上，且 `pyproject.toml`/`uv.lock` 独有） | 同上 |
| `fix/dependabot-security-oct-2026-10-24` | 2 | 6 | 否 | 非死枝（vs 本地 `main` 有 2 个 `+`，未完全并入） | 同上 |
| `main` | 6 | 352 | 否 | **长期分叉线**（见 ③） | 每次「合入 main」动作后必须重跑本节 |
| `mirror/nl2sql-ttl-and-006-slim` | 5 | 350 | 否 | 公开镜像侧载体，**按 #5 单独算，不混入内网计数** | 下一次 publish 模式推镜像时：若公开基线已含该树 ⇒ 原地**追加**而非新建第二条 `mirror/*` |
| `feat/nl2sql-ttl-and-006-slim` | —（当前线） | — | — | 工作线本体 | 工作线应短命（<24h）——它相对 `main` 的最早独有提交为 2026-10-15（`af19b5cf`）、最新为 2026-10-28（`896f966e`），**跨 14 天 ⇒ 已违反分支模型**。处置同②③，需人定；触发复审 = 一旦该线合入任一集成分支并当场删本地/远端，本行从表里消失 |

**死枝计数 = 1**（`feat/nl2sql-meta-build-recovery`）⇒ AGENTS.md #3 的「死枝 >1 当周处理」未触发。**当日已按订正流程退役删除该条**（本地分支 9 → 8），过程读数见下一小节。

#### 订正与执行结果（同日两轮）：首判不完整 ⇒ 补文档层判据 → 用户批示 → 先合后删

**第一轮（判据不完整）**：拓扑三件齐只回答「删了会不会丢内容」，没回答「它有没有被写在文档里的决策指名保留」。实取：`docs/adr/0012-nl2sql-branch-consolidation.md` **§2 决策**原文 = 「保留 `feat/nl2sql-meta-build-recovery` 为**唯一** nl2sql 集成分支」，而且同件 **§4 行 44（2026-10-27 体检）早已预判过同一件事**：「按 §2 它是保留的唯一集成分支，**0 独有不构成死枝判据**」并附了 `git cherry` 对 squash 合并失效的方法告警。⇒ 本轮首判是**没读完同件就下结论**，不是“ADR 与新发现冲突”。

**第二轮（用户批示后执行）**：用户原话「删分支前，先将分支合并至当前分支，避免内容丢失」⇒ 触发 §4 行 44 登记的复审条件「用户明确批示处置」。三步实取：
1. `git merge --no-edit feat/nl2sql-meta-build-recovery` → **`Already up to date.`**（no-op），HEAD 仍 `896f966e`、合并前后 `git status --short` 逐行相同 ⇒ 未提交改动未被触碰；
2. `git branch -d` **被拒**，理由 = 未合入其 upstream `github-legacy/…`（本地 tip `f6a6b9d8` 领先镜像侧 tracking ref `a0e7b8ef`）；补取两条硬判据：`is-ancestor 本地→HEAD` rc=0、`rev-list HEAD..镜像侧 tracking ref` = **0** ⇒ 两侧内容均全在当前线，删 ref 不丢提交；
3. 先在 ADR-0012 §4 写下退役结论（#1 要求的“确证”）⇒ 再 `git branch -D`，输出 `Deleted branch … (was f6a6b9d8)`；**独立复验**：`for-each-ref refs/heads` 已无该枝（9→8）、`is-ancestor f6a6b9d8 HEAD` rc=0、HEAD 与工作区未变。

可复用的两条：**死枝三判据是拓扑层的，删一条被 ADR 命名过的分支还须过文档层**（与 `check_doc_sync` 扫不到 `docs/` 内部引用同一类盲区）；以及上面纪律段里的 **`-d` 校 upstream 不校 HEAD** 规则。

### 4. worktree 面（实测）

```
主工作区                                      896f966e [feat/nl2sql-ttl-and-006-slim]
.codeartsdoer/temp/wt-meta-review             12f03c8f (detached HEAD)
```

- 无分支被 worktree 占用 ⇒ `git branch -d` 不会因占用拒删。
- **订正一条旧登记**：`docs/adr/0013-semantic-cache-single-track.md` §9 行 56 第 ④ 项登记的 `.tmp-scratch/wt-main`（钉在 `fix/dependabot-security-int` 上）本轮**不在 `git worktree list` 里** ⇒ 该登记已过时（复审触发条件「worktree list 实测不含它」已满足）。ADR-0013 那行自称「时点快照，换 rev 后必须重取」，故**不在那里改写**，以本节为准。

### 5. 本轮未做（诚实边界）

- **执行了 1 条本地删除**（`feat/nl2sql-meta-build-recovery`，先合后删，全过程与判据见 §3 订正小节）；其余 7 条本地分支**一条未动**（`company-snapshot` 虽标为冗余也**未删**，那需单独批示）。未推远端、未 `git fetch --prune`（fetch 会改动 `refs/remotes/*`，属另一回事）。未跑项：下面 §6 已把其中一条补上，**剩下的仍未做 = `git fetch --prune`**。
- 日期均为 author date（`%ad`），未校与 committer date 的一致性。
- ~~`github-legacy` 现态未取证（网络层 rc=128）~~ ⇒ **已由下方 §6 节闭合**（同日补测 rc=0）。
- 表内「独有文件」数是 3-dot diff（merge-base 起算）；对异宗的 `company/main` 该口径失效，故那一列只作旁证、判据以 `cherry -v` + `merge-base --is-ancestor` 为准。**失效的具体机制见 §6.3**（不是“数字不准”，是“根本没有数字”）。

---

## 2026-10-29 补测节（同日 pass3；读数绑 HEAD `896f966e`，命令 `uv run python .tmp-scratch/c-mask/branch_health_pass3.py`，该脚本不入库 ⇒ 只作取证出处）

本节在上一节基础上只做了三件事：**① 把 `github-legacy` 从「未取证」变「实测」；② 订正上一节一处不是读数的读数；③ 新增一条报警**。拓扑其余结论未变（本地仍 8 条，逐条 `cherry+`/独有文件与上一节一致）。

### 6.1 远端面（本轮实测，rc=0）

| 远端 | heads | 读数与定性 |
|---|---|---|
| `company` | **1** | `refs/heads/main` 一条 ⇒ 不报警（同上一节） |
| `github-legacy` | **8**（计 `mirror/*` 外 **7**） | **>2 ⇒ AGENTS.md #3 的报警条件成立**。但成因不是本地积枝：8 条里 **5 条是 Dependabot 自动分支**（`dependabot/uv/*`×2、`docs/dependabot-*`、`fix/dependabot-*`×2）+ `main` + `mirror/nl2sql-*` + **一条我们已经退役删除但仍挂在公开仓的 `feat/nl2sql-meta-build-recovery`** ⇒ 详见 6.4 |

**本仓在公开侧的现态**（回答 #5 “镜像分支不累积第二条”能否做到）：
`git rev-parse` vs `git ls-remote` 逐项比——`github-legacy/main` 本地=远端 `88515cab`、`github-legacy/mirror/nl2sql-ttl-and-006-slim` 本地=远端 `2011fe6a`（两项均「一致 = True」）⇒ **下一批推镜像可在这两条既有分支上原地追加，不需新建第二条 `mirror/*`**。

### 6.2 登记一条对流程的偏离：本轮做了 `git fetch`

上一节 §5 写的是“未 fetch（fetch 会改动 `refs/remotes/*`，属另一回事）”。本轮**偏离了那条纪律**：
`git fetch github-legacy main mirror/nl2sql-ttl-and-006-slim`（rc=0，`ac4ebd32..88515cab` / `82dbf183..2011fe6a`）。
理由：不 fetch 就只能拿旧快照回答“公开侧现在漏不漏”，而那正是 `evidence-format.md` §1 字段 1 禁止的形状（状态绑旧 rev）。旧 sha 已登记在上括号内，可据此回查。**未做 `--prune`** ⇒ 本地跟踪面仍含陈旧项（见 6.5）。

### 6.3 订正：上一节 `company-snapshot` 那行的“独有文件 = 1”不是读数

实取：`git diff --name-only feat/nl2sql-ttl-and-006-slim...company-snapshot` ⇒
**`fatal: … no merge base`，rc=128，stdout 为空**；`git merge-base company-snapshot HEAD` rc=1。
⇒ 那一列对异宗分支**不是“不准”，是根本没有值**。上一节表里那个“1”的来源已定位：当时探针把失败哨兵字符串当成了一个文件名（本轮 pass3 初版重踩同一坑，报成“0”——同一个不存在的读数在两个脚本里分别读出 1 和 0）。
**为何要紧**：“独有文件 = 0”恰好是死枝判据，拿它当证据就会把一条**不该删**的分支判成可删。⇒ 纪律补一条：**凡 `A...B` 差量判据必须先校 `merge-base` 存在（rc=0），否则那一列记 `<无数字>` 而不是 0**。已写进 pass3 脚本的 `must_lines()` docstring。

### 6.4 新事实：退役分支的内容不在公开侧留下孤儿，但分支壳还在

判据（上一节 §3 行 62 登记的复审触发条件“若发现某 commit 只在 `github-legacy` 那条上”）：**未触发**。
实取：`git rev-list --count HEAD..github-legacy/feat/nl2sql-meta-build-recovery` = **0** ⇒ 该镜像侧 tip（`a0e7b8ef`）无 HEAD 不含的提交，退役结论在公开仓现态下仍成立。
但分支本体仍在公开仓：本仓 `github-legacy` 的 push URL 是禁用占位 ⇒ **从本机删不了它**，需先恢复推送权限——那是 D2，本文只登记不执行。

### 6.5 本地跟踪面陈旧项（实测集合差）

本地 `refs/remotes/github-legacy/*` = 9 分支 + 1 HEAD 符号引用，远端实况 8 heads ⇒
**本地陈旧 2 条**（远端已无：`dependabot/uv/major-cb6f23add6`、`dependabot/uv/minor-and-patch-0e126670a4`）+ **远端新增未取 1 条**（`dependabot/uv/minor-and-patch-0c5ebd9680`）。
⇒ Dependabot 在公开镜像仓上**持续自动开分支**（同一任务换后缀反复新建，说明公开仓的 dependabot 是启用态，而 `.github/dependabot.yml` 在公开树里）。这是“公开侧是个活仓”而非“只读快照”的证据，与《分支卫生》#4/#5 把镜像当“公开侧载体”的说法吻合。处置需拍板（D2）：要么关公开仓 Dependabot，要么把 #3 的“远端 >2”计数口径改为“只数 `company`”。

### 6.6 本节死枝计数

本地 8 条：**0**（`company-snapshot` 仍为候选冗余但按 6.3 不得用“独有文件=0”判它；其余 6 条均有独有提交或独有文件）。上一节已执行为 1 条退役 ⇒ 两节合计“发现 1 / 已清 1 / 本轮新增 0”，未触发“死枝 >1 当周处理”。
**复审触发条件**：`company-snapshot` 的 tip 不再等于 `refs/remotes/company/main`；或 `company` 远端那条快照被重写/删除 ⇒ 它升为唯一持有，禁删。

### 6.7 同日收尾复跑（与登记值逐项相同）与两条当场校准

命令：`uv run python .tmp-scratch/c-mask/branch_health_pass3.py`（rev `896f966e`，与 6.1–6.6 同树；脚本不入库，换机器须照本节判据自建）
读数：远端名 `company` + `github-legacy`（无 `origin`）；company heads = **1**；github-legacy heads = **8**（计入“恒 2”口径 **7** ⇒ 报警仍成立）。
本地 8 条逐条与 §3 表**按分支逐项相同**：`cherry+` 为 company-snapshot 2 / docs-round4 2 / pillow-13 3 / security-int 2 / security-oct 2 / main 6 / mirror 5；
独有文件为 `<无数字>`（异宗，见 6.3）/ 7 / 7 / 6 / 6 / 352 / 350；两个镜像 ref 本地=远端仍 True。
⇒ 本节与上一节的数字不是单次读数，同一棵树上可原地复跑得到同值。

两条当场校准（均为只读）：
- 6.6 的复审条件：**未触发**。`git rev-parse company-snapshot` = `git rev-parse refs/remotes/company/main` = `fe22794c5a…` ⇒ 本机无唯一持有，它仍是“可删候选”；**本轮未删**（删除需单独批示，上一节已登记该口径）。
- 6.5 的算术自洽：本轮 `git fetch` 后本地 `refs/remotes/github-legacy/*` 分支数 = **10**（不 prune），远端实况 = **8** ⇒ 10 − 8 = **2** 条陈旧，与 6.5 所述一致（fetch 前是 9，故“陈旧 2 + 远端新增 1”与 fetch 后的 10 并不矛盾）。

### 6.8 把体检脚本化（第四版），并记下脚本自己踩的四坑

命令：`uv run python .tmp-scratch/c-mask/branch_health.py`（rev `896f966e`，与 6.1–6.7 同树；只读，不 `branch -d`、不 `fetch --prune`；脚本不入库）
读数（`目标 | 命令 | 读数 | 结论` 四列已在脚本输出里成形，此处只摘判据行）：

| 项 | 读数 | 与登记的差异 |
|---|---|---|
| 远端名 | `git remote` 现取 = `company` + `github-legacy`（无 `origin`） | 与 #3 一致；不再硬编码 |
| company heads | 1（ls-remote rc=0） | 同 6.7 |
| github-legacy heads | 8，其中 `mirror/*` = 1 ⇒ 计入“恒 2”口径 **7** ⇒ **报警成立** | 同 6.7；报警按远端分列后才不会被误读成“公开镜像也违规” |
| 本地 8 条死枝判定 | 死枝候选 **0**；判据不适用 **1**（`company-snapshot` 异宗 ⇒ 独有文件列记 `<无 merge base>`） | 同 6.6/6.3 |
| 6.6 复审条件 | tip 两侧均 `fe22794c5a` ⇒ **未触发**（登记原文：“tip **不再**等于 main”才是触发） | 同 6.7 |
| 跟踪面 | `refs/remotes` 总 12 = 符号 HEAD 2（`company`、`github-legacy`）+ 分支 **10**；github-legacy 本地 9 / 远端 8 ⇒ 陈旧 2 + 远端新增未取 1 | 与 6.5/6.7 的“10 / 8 / 2 / 1”逐项相同 |
| worktree | 条数 2（其中 detached 1） | 新增可见面：删分支前须看占用 |

四个“探针自己的错”（都是同一个根：拿输出形状之前先猜了形状）：
1. **复审条件极性写反**：初版把“tip 相等”打成“已触发”，与 6.6 登记原文正好相反。⇒ 本版把**登记原文当作列内容**写进表里，判定只能跟着原文走，不得自己重定义“触发”。
2. **`for-each-ref` 用制表符分隔会丢行**：`github-legacy/mirror/nl2sql-ttl-and-006-slim` 这一行返回时不带 `\t`（12 行中只它没有），`split("\t")` 后分支口径读成 9。成因未查（不把猜测当结论）；换 `|` 分隔后 12 行全带分隔符。差一步就把“10 vs 8”的算术自洽读成“9 vs 8”。
3. **符号 HEAD 混进分支计数**：`refs/remotes` 里有 2 条是 HEAD 符号引用（不是分支），不分开列就会把 12 当成“本地又多了 2 条分支”。⇒ 口径必须写在读数旁边（与 6.5 同病：同一件事不同取法给不同数）。
4. **`git worktree list` 默认版没有 `worktree ` 行首**（那是 `--porcelain` 的格式），拿它筛 ⇒ 2 条读成 0。现改用 `--porcelain`，且**不打印绝对路径**（本机路径不入库）。

另外一条工具链事实（本轮当场实取，非脚本内容）：`git branch -r` 默认把符号 HEAD 显示成带 ` -> ` 的行（本仓实取前两行即 `company/HEAD -> company/main`、`github-legacy/HEAD -> github-legacy/main`），故“过滤 ` -> `”得到的 10 与 `for-each-ref` 扣除符号项得到的 10 **同值**（两套取法互校）。本节只新增登记，**不动 AGENTS.md 条款**（“公开镜像 >2 是否计入报警”的口径变更仍挂在待拍板，见 6.5 末句）。

---

## 2026-10-30 节（同月换 rev 原地复跑；读数绑 HEAD `89f0103a`，工作线不变）

> 本节不是新一轮体检，是一次**换 rev 复跑**：上一节（2026-10-29，绑 `896f966e`）登记的每个数在今天的树上还成立吗。
> 命令面 = 本文开头《命令面》那五条（均为入库可重放）。本机另有一份等价探针 `.tmp-scratch/c-mask/branch_health.py`（第四版），
> ⚠ 它住在 gitignored 目录（`git check-ignore -v` 命中 `.gitignore:61:.*/`，`git ls-files -- .tmp-scratch` = 0 行）
> ⇒ **不当核对路径**，只当效率工具；表里每个数都能用《命令面》那五条逐条重取。

| 项 | 2026-10-29 登记 | 本轮读数（rev `89f0103a`） | 判定 |
|---|---|---|---|
| 远端名 | `company` + `github-legacy`（无 `origin`） | `git remote` 同值 | 未漂移 |
| `company` heads | 1 | 1（`ls-remote` rc=0） | 未漂移，不报警 |
| `github-legacy` heads | 8（计入“恒 2”口径 **7**）⇒ 报警成立 | 8 / 7 | 未漂移，报警仍成立 |
| 本地分支条数 | 8 | 8 | 未漂移（本 7 批全提交在当前线，未新建分支） |
| 死枝候选 | 0（另有 1 条判据不适用 = `company-snapshot` 异宗） | 0（同样 1 条不适用） | 未漂移 |
| 逐条 `cherry+` | 2 / 2 / 3 / 2 / 2 / 6 / 5 | 逐项相同 | 未漂移 |
| `company-snapshot` 复审条件 | 未触发（两侧 tip 均 `fe22794c5a`） | 未触发（仍相等） | 仍是可删候选，本轮**未删**（删除需单独批示） |
| 跟踪面 | 分支口径 10；`github-legacy` 本地 9 / 远端 8 ⇒ 陈旧 2 + 未取 1 | 同值（陈旧合计 2） | 未漂移；`git fetch --prune` 本轮**仍未做**（D2） |
| worktree | 2 条（detached 1） | 2 条（detached 1） | 未漂移 |

**本轮真正变化的两项**（都是“自己动了线”的直接后果，不是新发现）：
- 当前线相对 `main` 的独有提交 **339 → 346**（`git rev-list --count main..89f0103a`）；差值 = 本轮批次
  （`git rev-list --count 896f966e..89f0103a` = **7**）⇒ 算术自洽。两个数都写成显式 rev 而不是 `HEAD`，
  否则后人复跑得 347 / 8，再把它们误读成“登记值漂移”。
- 分支年龄：工作线最早独有提交仍是 `af19b5cf`（author date 2026-10-15），tip 现为 `89f0103a`（2026-10-30）
  ⇒ **跨 15 天**。“分支短命 < 24h”那条违规在扩大，不是新增违规。

**本节不执行任何删除 / 推送 / fetch（含 `--prune`）**。上一节登记的三条 D2（公开侧镜像分支处置、`company` 无集成分支的拓扑、
Dependabot 在公开仓活跃）本轮**一条未解**，表中读数只是复述。

## 2026-11-02 节（换月复跑；**只跑命令面第 1/2/5 步，第 3 步逐枝与第 4 步 worktree 面本轮未跑**；读数绑当日最终 rev `0b4c1f37`）

本节不是新增一轮完整体检，而是把「远端 heads 从 2 变 3」这件已经发生的事按命令面重新取一次，
并把拓扑那条 D2 的结论从「挂着」改成「已拍板为例外登记」。

| 项 | 本轮现取（2026-11-02，UTC 日） | 与 2026-10-30 节对比 |
|---|---|---|
| 远端名（第 1 步，`git remote`） | 2 条：`company` + `github-legacy`（仍无 `origin`） | 未漂移 |
| `company` heads（第 2 步） | **3 条** = `feat/web-visual-poc` @ `0b4c1f37` / `lineage/intranet-v3-until-2026-10-19` @ `12f03c8f` / `main` @ `fe22794c` | 1 → 3（第十七批推上两条 ref 后第一次换月复取） |
| 「>2 报警」判定 | **命中 3 ⇒ 报警位触发**，但读数不解释为违规：解释口径见 `docs/adr/0014-web-poc-integration-branch-exception.md` §2 第 2 条（锚 ref 不计入「工作分支」维度） | 上一节的「不报警」是因为当时只有 1 条 |
| 本地分支（`for-each-ref refs/heads` 计数） | 10 条 | **未做逐枝死枝判定**（第 3 步未跑 ⇒ 本行只是计数，不能读成「本地无死枝」） |
| `company/*` remote-tracking | 4 条（3 heads + 1 HEAD 符号引用） | 与远端实况同值，本轮无陈旧项 |

**本轮未做的动作（诚实边界）**：未跑第 3 步逐枝独有提交与第 4 步 worktree 面・未 `git fetch`（含 `--prune`）・**未删任何分支**（含那条可删候选 `company-snapshot`，它仍需单独批示）・未动 `github-legacy` 的 pushurl 禁用位。`main` 与上一节同 sha `fe22794c` ⇒ 「不动 main」在本节仍是可复取的读数而不是口头承诺。

## 2026-11-02 步 3 补跑节（第十九批，同日；**首次真正跑逐枝三列**；读数绑 `c9622fdc`）

上一节自己点名的欠项是「第 3 步未跑 ⇒ 本行只是计数，不能读成本地无死枝」。本节就是把那一步补上，并且它当场抬出了**一条三列全命中的本地死枝**——这正是「计数不能当判定」那句话的实物形式：补跑前本地 10 条分支里 1 条是死枝，只跑计数的那一节读不出来。

**base 的取法（口径随 ADR-0014 改）**：`docs/adr/0014-web-poc-integration-branch-exception.md` §2 第 1 条已把 `feat/web-visual-poc` 认定为唯一集成分支，所以本轮 base 取它（@ `c9622fdc`），不再取上一节用的那条旧工作线。base 换形的后果要如实写：**换 base 会改变「独有 commit」的分母**，因此本表与 §3 那张表**不同基**，禁止跨表比数值。

三列口径与守卫（件 `.tmp-scratch/ap-visual/e24-00-<时刻>-monthly-step3.txt`，只读、不动任何 ref、不 fetch）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e24-monthly-step3.ps1
```

| 分支 | cherry `+` | 独有文件 | 是 base 祖先 | 分类 / 本轮处置 |
|---|---|---|---|---|
| `company-snapshot` | 2 | `<无数字>`（异宗，无 merge-base） | 否 | 冗余本地副本（tip == `company/main` 均 `fe22794c`）⇒ **仍是可删候选，本轮未删**（需单独批示） |
| `docs/dependabot-round4-2026-10-24` | 2 | 7 | 否 | 非死枝 |
| `feat/nl2sql-ttl-and-006-slim` | **0** | **0** | **是** | **死枝（三列同时命中 AGENTS.md 分支卫生 #1 的判据①）⇒ 本轮当场 `git branch -d` 退役** |
| `feat/web-visual-poc` | —（base） | — | — | 集成分支本体 |
| `fix/dependabot-pillow-13-2026-10-24` | 3 | 7 | 否 | 非死枝 |
| `fix/dependabot-security-int` | 2 | 6 | 否 | 非死枝（与 §3 那轮的「6 个独有文件」同值，未漂） |
| `fix/dependabot-security-oct-2026-10-24` | 2 | 6 | 否 | 非死枝 |
| `lineage/intranet-v3-until-2026-10-19` | 99 | `<无数字>`（异宗） | 否 | 历史锚 ref ⇒ 按 ADR-0014 §2 第 2 条**不计入**「工作分支」维度 |
| `main` | 6 | 352 | 否 | 长期分叉线；每次「合入 main」动作后必须重跑本节 |
| `mirror/nl2sql-ttl-and-006-slim` | 5 | 350 | 否 | 公开镜像侧载体，按分支卫生 #5 单独算，不混入内网计数 |

⚠ 两个 `<无数字>` 不是「读不出来的 0」：§6.3 那条纪律（异宗分支的三点差量**没有值**，写 0 就会把一条不该删的分支判成可删）在本轮是**被执行**的而不是被引用的——脚本对每条分支先跑 `git merge-base` 判有无公共祖先，无则记 `<无数字>`。

**死枝计数 = 1，且本轮当场处理** ⇒ AGENTS.md #3 的「死枝 >1 当周处理」未触发（1 条不需要等当周）。

### 退役执行读数（唯一一条被动的 ref 删除）

| 动作 | 实取 |
|---|---|
| `git branch -d feat/nl2sql-ttl-and-006-slim` | stdout `Deleted branch feat/nl2sql-ttl-and-006-slim (was d140f91f).`，rc=**0**。用的是 `-d`（自带「已合入」检查，删不动会当场拒绝），**不是 `-D`** |
| 本地 heads 条数 | 10 → **9**（`for-each-ref refs/heads` 复取） |
| 有没有丢 commit | `git cat-file -t d140f91f` = commit・`git merge-base --is-ancestor d140f91f HEAD` rc=**0**・`896f966e` 同法 rc=**0** ⇒ 台账曾绑定的两个 rev 都仍在 HEAD 祖先链上，删的只是 ref 名 |
| 远端面 | `company` 从未有过该分支（本轮 ls-remote heads=3 内无它）⇒ 本轮**零远端动作**；`mirror/nl2sql-ttl-and-006-slim` 那份公开载体仍在（独有文件 350） |
| 代价（必须登记，不能只报收益） | 该**分支名从此不再解析**：`git rev-parse --verify feat/nl2sql-ttl-and-006-slim` rc=**128**；`git grep -c` 实取全仓 `docs/` 下有 **38 处**引用（分布在 10 个文件，单份取证件里 20 处）以它为坐标。⇒ 口径：**历史取证台账里的分支名不回填**（那是当时的实物，改了就是篡改快照），复跑旧命令时以当时登记的 sha 取代名；**不得为了让旧命令能跑而重立同名 ref** |

**复审触发条件（分支卫生 #2：没这条不许登记）**：
1. 若发现任何 commit 只存在于已删的那条线上（判据 = `git log --all --not HEAD` 非空，或某 sha 只在 `mirror/nl2sql-ttl-and-006-slim` 的树里）⇒ 从镜像侧 fetch 回来**重立**该 ref 并推翻本轮结论；本轮删枝的正当性完全建立在上面那行「三列全 0 / 是祖先」的可复跑读数上，不建立在记忆里。
2. 若 `docs/` 里出现**必须按分支名**才能复跑、且 sha 形式无法替代的取证命令 ⇒ 说明「不回填、按 sha 复跑」这条口径在该处不成立，回到本节重写处置。
3. `company-snapshot` 的复审条件沿用 §3 那行原话（`refs/remotes/company/main` 仍在 ⇒ 本地这条无唯一持有 ⇒ 可删；远端那条被重写/删除 ⇒ 升为唯一持有，禁删）。本轮两侧仍同 sha，**未删**。

**本轮仍未做的动作（诚实边界）**：第 4 步只顺手取了 `git worktree list`（2 条，detached 1，与上一节同值）⇒ **worktree 逐项清理判定仍未跑**・未 `git fetch --prune`（跟踪面陈旧项仍在）・未删 `company-snapshot`・**远端一条分支也未动**（未推、未删、未 force）・未动 `github-legacy` 禁用位・未推 `mirror/*`。另需说明：本节的删枝动作**只发生在本地**，所以上一节「远端 heads = 3」的读数在本轮复取后仍是 3，未因删枝而变。

