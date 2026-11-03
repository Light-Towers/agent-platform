# CI 执行面真实化方案（2026-11-02）

> **状态：Proposed（D2 待拍板）**。本件**零代码改动**：未新建/修改 .gitlab-ci.yml（该路径**本仓从未存在**，故全文不带反引号——反引号在本仓的口径是「按仓库根可解析」）、未改 workflow、未动 `Makefile`、未推任何 ref。它只回答一个问题——**`make ci` 这扇门到底在谁的地面上关过人**，以及要让它对「内网这份内容」生效需要先取证什么。
> 取数基准 = 内网 `feat/web-visual-poc` @ `3e1eeae3`，2026-11-02 夜现取。**每个数都带复现命令，引用前先复跑**（本批新踩的一次表述证伪见 §2 末）。

## 0. 问题空间

工单件 §12 与 ADR-0014 反复用的一句「推到远端 ≠ 门禁执行」是对的，但它把两件不同的事压成了一句：**有没有一扇门**，和**那扇门咬的是不是这份内容**。本轮取证发现第二半比第一半更麻烦——服务端确实有一扇有齿的门，而且红过很多次，只是它一辈子没咬过我们这个分支上的任何东西。

所以本件的射程：
- **在**：把「执行面」的实物边界钉下来；给出四条候选路径的成本与判据；列出需要先取证的未验证项。
- **不在**：任何具体的 CI 配置文件内容（那是落地刀的事，且需先过 §7 的 D2）。

## 1. 现状取证表（2026-11-02 现取）

公开侧仓库 = `github.com/Light-Towers/agent-platform`，即本地那个 pushurl 被禁用的 `github-legacy`（公开脱敏镜像）。读数全部经 `gh api` 现取，取证目录是 gitignored 的 .tmp-scratch/ap-visual（**故意不带反引号、不入库**），本轮三件 = e25-01-gh-all-runs.tsv（1555 行）・e25-03-gh-ci-steps.txt・e25-04-gh-run-steps.txt。

| 读数 | 值 | 复现 |
|---|---|---|
| Actions 全量 run 数 | **1555**，跨度 `2026-08-12T04:54:07Z` → `2026-10-28T16:52:46Z` | `gh api 'repos/Light-Towers/agent-platform/actions/runs?per_page=100' --paginate --jq '.workflow_runs[] \| [.run_started_at, .name, .head_sha, .head_branch, .event, .status, .conclusion, .id] \| @tsv'` |
| 其中 `agent-platform-ci` | **609**（success **430** / failure **179**） | 同上按 `.name` 过滤 |
| 其余主力 workflow | `agent-platform-ha` 288・`ha-assembly` 218・`Push on main` 77・`eval-llm` 38，剩下的尾名是 dependabot graph-update 与 CodeQL 派生作业 | 同上 |
| 按事件 | push 743・dynamic 402・pull_request 372・schedule 38 | 同上按 `.event` |
| **内网工作线四个 sha 的 run 数** | `0b4c1f37` = **0**・`1960d7a6` = **0**・`c9622fdc` = **0**・`3e1eeae3` = **0** | 对 TSV 逐字 `Select-String -SimpleMatch <完整 40 位 sha>` |
| 公开 `main` tip | `88515cab` = 本地 `main` = `github-legacy/main`（三者同值），提交是 `chore(deps): bump langfuse (#129)` | `git log --oneline -1 88515cab` |
| 该树的 `web/` 文件数 | **0** | `git ls-tree -r --name-only 88515cab -- web \| Measure-Object` |
| 最近两次 ci run 的步骤清单 | `40696249793`（2026-10-28，head `2379f23a`）与 `40169577987`（2026-10-25，head `88515cab`）都是：Set up job / checkout@v7 / Install uv / Set up Python / Install / **CI gate** / **Doc sync check** / Post… / Complete job ⇒ 含 `Web gate`、`corepack`、`ci-web` 的行命中数 = **0** | `gh api 'repos/Light-Towers/agent-platform/actions/runs/<id>/jobs' --jq '.jobs[].steps[] \| [.name, .status, .conclusion] \| @tsv'` |
| 两宗的 commit 交集形状 | run 清单里 **439** 个不同 head_sha：本地可解析 **322** / 本地**不可解析 117**（例：`2379f23a` = PR **#147** 的 dependabot head，`state=open` 至今未合） | 逐 sha `git cat-file -t`；`gh api 'repos/…/commits/<sha>/pulls'` |
| 内网那 39 行 workflow 在公开侧的存在性 | `git diff --numstat main HEAD -- .github/workflows/` = `agent-platform-ci.yml` **+39 / −0**、`ha.yml` +11 / −2 | 同命令 |
| 内网 GitLab CI 入口 | 无。路径 .gitlab-ci.yml **全历史零命中**（`git log --all --oneline -- .gitlab-ci.yml` 空输出），`git ls-files` 无 gitlab 命名文件 | 同命令 |
| 内网 GitLab 评审入口 | **有**（刀㉓ EXECUTE 的服务端回显含 merge request 创建链接，台账 §26.2） | 复跑推送件的 PROBE 通道读回显 |
| 公开镜像推送位 | `github-legacy` pushurl = `DISABLED-no-push` | `git remote -v` |

## 2. 三种绿（本件的核心区分）

| 名称 | 谁执行 | 当前状态 | 能证明 | 不能证明 |
|---|---|---|---|---|
| **本地绿** | 我的机器：`uv run pytest` / ruff / 面禁件 / typo-scan | **唯一常跑的一档**，每刀提交前都跑 | 这份源码在**我这台 Windows + uv** 上成立 | 换环境是否成立（内网宿主是 Py3.10 + 无 uv，见 126 那节）；也没证明"有人守" |
| **容器绿** | 241 上的容器跑 `gate.sh` / `make ci-web`（刀⑲ 实跑，判据 D = 200 + no-store） | 已成立两次（构建 + 修复后重建），**需人发起** | 依赖树 454 包 + 真 Linux 语义下成立 | 不自动、不拦人；一次没跑就是一次没有 |
| **服务端绿** | GitHub Actions（公开宗跑过 609 次 ci，其中 **179 次 failure**）/ 内网 GitLab（无 CI 入口） | 对**内网工作线 = 从未发生**（四个 sha 全 0） | 公开宗那 179 次红证明这扇门**真的有齿**，不是装饰 | 齿咬的是别人的提交（dependabot bump）；对 `web/` 连"声明"都没有 |

**一条表述订正（本件自带）**：在册的「CI runner 仍未实跑」（取证件 §26.6、刀㉔ 提交信息）**不准确**。准确说法是——runner 在公开遮敏宗执行过 1555 次（含 `agent-platform-ci` 609 次、179 次 failure），**但内网工作线零 run**。

栽这一跤的形状值得单独记：我当时核的是「本机与内网都不可达 GitHub」（= **我能不能发起**），从没核「服务端历史上跑没跑过」（= **它跑过没有**）。两者是不同的读数，缺任一个都会写出方向相反的错句。⇒ 新口径：**任何关于「有没有执行面」的陈述必须同时给「谁能发起」与「历史上跑没跑」两个读数**，只给一个就不许落进文档。§6 反证表 N5 是这条口径的机械形式。

## 3. 为什么「服务端跑过」不等于「我们的门禁在守」

1. **内容不等价**。公开宗是「遮后内容 + 自己独立演化」的宗：117 个 run-head sha 在本地不可解析，PR #147 至今 open；反向看，本地 `main` tip 那棵树里 `web/` **一个文件都没有**。⇒ 刀⑲ 给 `agent-platform-ci.yml` 加的那 39 行（`web/**` 两个 paths + Web gate 步 + 语义缓存契约步）**只存在于内网 feat 线上**，服务端从未见过它，连解析都没发生。
2. **触发权不在我们手上**。Actions 只在推送到那个公开仓时触发，而推送位是显式禁用的（`DISABLED-no-push`，公开镜像闸门）。
3. **有齿的证据是真的，但齿没咬过我们**。609 次 ci 里 179 次 failure 是硬的，问题只在于这些红全部发生在公开宗的提交上。

⇒ 「推到远端 ≠ 门禁执行」这句要升级为**三段**：**推到远端 ≠ 门禁执行 ≠ 执行的那扇门咬的是这份内容**。中段断在「内网仓没有 CI 入口」，末段断在「有入口的那一侧看不到这份内容」。

## 4. 四条候选路径

| 路径 | 一句话 | 成本 | 能否对**内网内容**生效 | 决策级别 |
|---|---|---|---|---|
| **A. 借公开镜像跑 Actions** | 把内网 feat 线遮成 mirror 分支推上去，让既有 609 次的门跑它 | **最低**（基础设施在位、runner 免费、门禁步骤现成） | **不能**——跑的是遮后内容；且必须先解禁 `github-legacy` push | **D3**（公开历史不可回收，误推一次即外泄）⇒ **拒为常规路径**，只允许"一次性、显式申报、逐文件遮好"的例外，且例外本身要单独批 |
| **B. 内网 GitLab CI** | 一个 .gitlab-ci.yml + 一个 runner，让服务端对**内网这份内容**执行门禁 | 中：runner 归属/注册是基础设施事项，不在本仓控制面内 | **能**（唯一真解） | **D2**（人定；AI 只给 §7 那三条前置读数） |
| **C. 把容器绿常态化** | 不新增服务端：给 241 那轮 `gate.sh` 固定件号与判据，每批必跑并入账 | **最低且今天就能做**（形状已存在，刀⑲ 已实跑两次） | **部分能**——内容对（跑的就是内网 checkout），但没有自动触发点，仍是人发起的例行作业 | **D1**（AI 提议、人批形状） |
| **D. 维持现状** | 本地绿 + 偶发容器绿 | 零 | 不能 | 现状即 D，**必须显式登记为债**而不是默认背景 |

推荐顺序：**C 立刻做**（不需拍板，只把已有形状固定下来）→ **B 的三条前置取证**（这一刀不需要人决策，取证本身是只读的）→ 取证成立才谈 B 落地 → **A 拒**。不要把 C 写成 CI：它是"有 ID 的例行作业"，写成门禁就是又一次「接线当启用」。

## 5. 迁移策略（三步，每步可逆）

- **步 1（走 C）**：容器门禁的发起固化为「一批一件号 + 判据不缩」。零仓内文件改动，回退 = 不再跑，账面自曝。**不得**在台账里把这一档写成「CI 已过」。
- **步 2（B 的前置取证，只读）**：现取三条读数——① 内网 GitLab 是否给本项目提供可用 shared runner；② 项目设置里能否注册 runner（谁有权限）；③ runner 若有，executor 是 docker 还是 shell（决定能不能直接 `make ci`）。这三条决定 B 是「本仓加一个文件」还是「先提基础设施申请」。**机器放置约束（取证时即带）**：runner 不放 126（`ROTA=1` 单盘 + 常态化 IO stall 会连带打死同机观测栈，见 AGENTS.md 内网那节第 6/7 条）；125 满载他项目，不进去加 IO。
- **步 3（B 落地，仅当步 2 成立且人批 D2）**：先建**最薄**一版 .gitlab-ci.yml——单个 job 只调 `make ci` 的 lint + doc-sync 子集，**非阻塞**观察一轮；确认 job 真的在跑（判据 = pipeline 的 sha 与本地 HEAD 逐字相等，见 §6 N1）后再扩到 `make ci` 全量与 `make ci-web`。**扩面前不改任何产品代码，也不把 Makefile 真相源拆成两套**（job 里只出现 `make …`，不重写命令）。回退 = 删那一个文件，MR 评审照旧手工。

## 6. 验收判据 + 非空转反证表

按 `docs/operations/evidence-format.md` §4 的形状：每格都要回答「如果这一格其实没跑，它会伪装成什么」。

| 格 | 动作 | 期望读数 | 若「没跑」会伪装成 | 反证（必须实跑，不是推演） |
|---|---|---|---|---|
| **N1** 服务端首条真绿 | 内网 sha 上出现一条 pipeline/run | `status=success` **且** 该 run 的 head_sha 与本地 HEAD 完整 40 位**逐字相等** | 「界面是绿的」但绿在别处 | 拿一个已知会红的改动上去，必须读到 `failed`；读不到 = job 没执行 |
| **N2** Web 门禁在服务端跑 | run 的步骤清单含 `Web gate` | 命中 ≥ 1 | 公开宗永远不会有这格（`web/` 不在那儿）⇒ **只能在 B 路成立**，拿 A 路的绿填这格就是假绿 | 本轮基线已实取：最近两次公开宗 run 命中 = **0** |
| **N3** 语义缓存契约步 | 有 valkey service 且带 `CACHE_CONTRACT_REQUIRED=1` 的步骤存在 | 步骤存在且 rc=0 | 「服务没起 → 用例没跑 → 静默变绿」，这正是 `Makefile` 那个必填开关防的事 | 把 `CACHE_CONTRACT_REQUIRED` 置 0，必须读出**明示 skip** 而不是空成功 |
| **N4** 门禁有拦截力 | 故意的红提交 → 合并被阻断 | pipeline `failed` **且** MR 不可合 | 只有红、没有阻断 = 装饰（本格还需 GitLab 保护分支设置读数，**本件未取**） | 未取得，故 N4 现为**待取证**，不许记成已过 |
| **N5** 反「公开宗绿替内网背书」 | 引用任何 CI 状态时必须并列两个 sha：run 的 head_sha 与本地 HEAD | 两者不等值 ⇒ 该读数**不得**被引为本项目门禁历史 | 「Actions 跑过 1555 次」被读成「我们的门禁历史」 | 本轮已实跑：四个内网 sha 的 run 数 = **0/0/0/0** |

## 7. 决策点（谁定）与未验证项

- **D1**（AI 提议、人批）：C 的常态化形状（件号规则、判据不缩、账面上怎么标）。
- **D2**（人定，AI 给证据）：B 是否立项——含 runner 归属、机器放哪、谁维护、失败谁修。**§5 步 2 的三条读数没取之前，这个决策没有意义**。
- **D3**（禁止自动）：解禁 `github-legacy` push・把内网分支镜像到公开宗（A 路）・任何 force・动 `main`。
- **未验证项（不得当事实引）**：内网 GitLab 是否有可用 runner；executor 类型；MR 是否配了流水线必过的保护；`deploy/k8s/README.md:213` 那条 gitlab-runner apt 源只是**当年装过源的痕迹**，不是 runner 存在性的证据。

## 8. 明确不做（本件射程外）

不动 .gitlab-ci.yml（连新建都不做）、不改 workflow、不动 `Makefile`；不为「有 CI 跑」把 `make ci` 拆成两套真相源；不把 mirror 分支推上去当验收；不动那两件 `docs/tech-debt/` 未跟踪文件（用户 2026-11-02 拍「别动它们」）；**不推任何 ref**（刀㉔ 与刀㉕ 都保持未推，ahead=1/2 原样）。

## 9. 复跑块（只读，无破坏性动作）

```powershell
gh api 'repos/Light-Towers/agent-platform/actions/runs?per_page=100' --paginate --jq '.workflow_runs[] | [.run_started_at, .name, .head_sha, .head_branch, .event, .status, .conclusion, .id] | @tsv'
gh api 'repos/Light-Towers/agent-platform/actions/runs/40696249793/jobs' --jq '.jobs[].steps[] | [.name, .status, .conclusion] | @tsv'
git ls-tree -r --name-only 88515cab -- web
git log --oneline -1 88515cab
git diff --numstat main HEAD -- .github/workflows/
git log --all --oneline -- .gitlab-ci.yml
git remote -v
```

⚠ 三个使用限制：① `gh api` 的数**绑取数时刻**，公开宗随时可能新增 run（本轮 newness 停在 2026-10-28T16:52:46Z），引用前复跑；② run 清单里的 head_sha 是**公开侧的 sha**，与内网同名提交无关（两宗不同 sha），所以比对只能用「逐字相等」而不是「短号相同」；③ 本节所有计数（1555 / 609 / 179 / 117 / 0）都是**工作树时刻快照**，不进散文引用，要引就先复跑上面那三条命令。
