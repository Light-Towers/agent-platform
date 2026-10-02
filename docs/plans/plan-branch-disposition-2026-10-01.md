# 分支资产台账与处置路径（2026-10-01）

> 类型：纯登记（不改代码、不动任何 ref）。目的：本轮分支清理的全部取证结论落库，避免后续会话重复推导或凭分支名猜"没用了"。
> 触发：用户要求清理"已处理完问题"的分支。判定纪律见文末「可复跑命令」。

## 1. 已清理（均为证据充分后的动作）

本轮清理：本地删 9 条（14 → 5，新建台账分支前）、远端删 4 条（`fix/dependabot-urllib3`、`fix/dependabot-eval-transitive`、`fix/dependabot-pyjwt`、`fix/main-dep-security-floors`），定性依据三类，逐条实测：

> 2026-10-02 又追加一轮（CodeQL Batch 7 系列 9 条），判据同上，取证与处置见文末 **§6**。

| 证据类型 | 判据 | 本轮实例 |
|---------|------|---------|
| 完全并入 | `git cherry -v <真实 base> <branch>` 行数全为 `-`（ahead=0） | `feat/courses-productionization`、`fix/deepagents-typed-memory`、`fix/intent-kernel-consolidation`、`fix/ws-monitor-shared-infra`、`fix/zhanggui-kg-real-query`、`v2`(本地)、`fix/dependabot-*` |
| squash 合并 | head **不是**目标分支祖先，但 head 与 merge commit 的 `git show --stat` 文件清单+增删行数逐项一致 | `fix/main-dep-security-floors`（PR #17：4 files +26/−6 与 `e5904c80` 完全一致） |
| 纯镜像 | 两 ref 的 `^{tree}` OID 相同 | `company-release` ≡ `company/main`（`f638624…`） |

**注意 base 陷阱**（本段 2026-10-02 重核订正）：原写「`feat/isolation-hardening` 的 PR base 是 **v3** 不是 main，按 main 算会得到 48 个假独有提交，按 v3 算才是 15」。该数字对**成文当时**为真（台账于 PR #41 合流**之前**测量），但 #41 把 v3 全量合入主干后结论已反转：今天按 main 算得 `git cherry -v origin/main feat/isolation-hardening` = 15 行（**8 个 `-` + 7 个 `+`**）。旧的 48 已不可复现（它的分母 main tip 本身已变），不拿它做减法求「多少条已入主干」，只记当下事实：真独有 = 7 条。⇒ 只拿 PR 记录的 `baseRefName` 不够，**还须复核该 base 今天是否仍存活、是否已被主干吸收**（否则会把活落在一条形同死分支的 ref 上）。实际并入时的 base 为 `main`，见 §3。

## 2. 保留的三条（2026-10-02 重核：其中 `v3` 的保留理由已失效）

| 分支 | tip | 相对基准（今日实测） | 为什么不能删 |
|------|-----|---------|-------------|
| `v3` | 26cd2fa（09-27） | **ahead 0 / behind 67** vs `main`（原记 ahead 47 / behind 19，**已失效**） | ⚠️ 原写的理由「主干尚未吸收」**错了**：PR #41（2026-10-01）已 `git merge origin/v3` 全量合入，且 `git merge-base --is-ancestor 26cd2fa origin/main` 退出码 0 ⇒ 内容零丢失风险。是否删 ref 不再是取证问题而是**组织决策**（长期集成分支名带里程碑语义，同 §4 `origin/v2` 的情形），建议先 `git tag archive/v3 origin/v3` 再删，**待拍板**。
| `feat/isolation-hardening` | d078312（09-28） | ahead 15 / behind 79 vs `main`（cherry 真独有 7 条）；相对 v3 曾为 ahead 15 / behind 12 | ~~不是债~~ → **已处置**：真独有 7 条（ADR-0005 T0 内核协议下沉 + 2 个 kernel 测试 + audit 真库修复 + testing-playbook + lint/uv.lock 收尾）已随 `feat/execution-memory-kernel-onto-main` 入主干（对主干净差 **+411/−23 / 11 文件**，非原记 vs v3 的 +842/−46）。PR #18 仍 CLOSED 未合，其 base `v3` 已不再是合理目标。 |
| `test/rag-route-ablation-eval` | 4cffe7c（09-30） | ahead 75 / behind 19 vs `main`（本行今日未重测） | **从未开过 PR**（`gh pr list --head` 返回空），即评审记录为零；且是唯一持有者（marker 计数见下） |

`test/rag-route-ablation-eval` 的唯一性取证（`git grep -c <marker> <ref>` 命中文件数）：

| marker | main | v3 | 该分支 | 含义 |
|--------|------|----|--------|------|
| `shutdown_tracing` | 0 | 0 | **7** | tracing 生命周期 shutdown 接线只在它身上 |
| `agent_runtime.otel` | 10 | 10 | 11 | 门面退役（`e086483`）未进主干，主干仍是旧门面 |
| `build_api_app` | 12 | 12 | **18** | 工厂装配站点更多（ks 迁 `build_api_app` + lint 白名单摘除，`b3c5c97`） |
| `RAGAS` | 1 | 1 | **7** | RAGAS adapter 接线 + 126 容器实跑（`4278e23`） |
| `ablation` | 12 | 11 | **25** | RAG 路别消融评测主体 |

## 3. 处置路径（2026-10-02 更新：第一条已执行完毕）

- ~~`feat/isolation-hardening` → 先解冲突再开 PR（base `v3`）~~ → **已执行，且 base 改为 `main`**（原写「唯一冲突文件 `scripts/audit_tenant_access.py`」只对 v3 成立；对 main 实为 **4 个文件**，多出的三个正是 PR #41 合流时手工处理过的那批：`knowledge_service/main.py`、`docs/adr/0005`、`plan-memory-hardening`）。取侧逐条记录在并入提交 `f666bc8` 的正文，及本文件 **§7**。
- **`test/rag-route-ablation-eval` → 拆分成小 PR 进 `main`**：75 个独有提交里混着两类主题（观测全局装配 / RAG 消融评测 + 演练记录）。整体开一个 PR 评审面过大；建议按 `refactor(observability)` 链与 `feat(eval)` 链各切一刀，且注意主干已发生 P2/P6/P7/P8 门禁收敛（PR #33 系列），重放时 lint 白名单需按现状重写。**开工前先用 §5 重测真独有数**——isolation 那条的先例是「账面 15 → 真独有 7」，本条的 75 很可能同样已大面积入主干。
- ~~`v3` → 与主干的合流是独立议题（47 commits）~~ → **已被现实关闭**：PR #41（2026-10-01）就是那次合流（`git merge origin/v3` 全量、不 cherry-pick、不用 `-X ours/theirs`），今天实测 v3 对 main ahead = 0。剩下的只是 §2 那条「是否删 `v3` ref」的组织决策。

## 4. 远端残余（需人工拍板，本轮未动）

- `origin/v2`：本地已删（内容确已并入），**远端保留**。名字带里程碑语义（CHANGELOG 有"见 v2 修复 #14"的交叉引用），删 ref 会丢历史锚点。若要清，建议先 `git tag archive/v2 origin/v2 && git push origin archive/v2` 再删分支。
- `origin/dependabot/uv/minor-and-patch-37a69dd668`：对应 **PR #26 OPEN**，是活分支，勿删。

## 5. 可复跑命令（任何"这分支没用了"的判断都须先跑这四条）

```bash
git fetch --prune
BASE=$(gh pr list --repo Light-Towers/agent-platform --head <branch> --state all --json baseRefName -q '.[0].baseRefName // "main"')
git cherry -v origin/$BASE <branch> | grep -c '^+'          # 0 = 内容已在 base
git rev-list --left-right --count origin/$BASE...<branch>    # behind / ahead
git merge-tree --write-tree origin/$BASE <branch> >/dev/null; echo $?   # 0 = 可干净合并
```

补充判据（按需）：`git show --stat <branch>` vs `git show --stat <merge-commit>`（squash 取证）、`git rev-parse "<a>^{tree}" "<b>^{tree}"`（镜像取证）、`git grep -c <marker> <ref>`（唯一持有者取证）。

**squash 场景的最强判据（§6 实例坐实）**：若 squash 提交的父就是分支的 fork 点，则 `git rev-parse "<branch-head>^{tree}" "<squash-commit>^{tree}"` 应**两个树 OID 完全相同**（比 diffstat 逐项比对更强，因为它是内容等价而非行数巧合）。该判据成立时，`git cherry -v` 仍会把分支的每个提交列成 `+`（patch-id 对不上单个压缩提交）、`git rev-list --left-right --count` 仍报 `ahead = 分支提交数`、`git merge-tree` 退出码也可能为 1——**这三个指标在 squash 已并入后均为假阳性，不得据此判“未并入”**。

**教训登记**：分支名里的 `test/` `fix/` `chore` 前缀不携带任何合并状态信息；`[gone]` 只说明远端已删；`ahead>0` 只说明未被 base 包含，不说明内容无价值。本轮两条"看起来最像垃圾"的分支（`test/…`、feature 收尾分支）恰恰是唯一持有者。

## 6. 追加登记（2026-10-02）：CodeQL Batch 7 系列 9 条分支处置

> 背景：Batch 7 / 7b / 7c / 7d / B7b-1 / B7b-2 连开 9 个 PR（#38〜#47）全部已合入 `main`，但分支未清。**取证先入库，再删 ref**（删完本地/远端 tip 就不可复现）。取证脚本：`.codeartsdoer/temp/branch_disposition_check.py`（只读，逐条跑 §5 四条命令 + PR 元数据 + 本地/远端 tip 对比）。

共同前提：9 条均 `base=main`（逐条从该分支 PR 的 `baseRefName` 取，非假定）、PR `state=MERGED`、本地 tip == 远端 tip（无未推送提交）。

| 分支 | PR | 落主干方式 | `cherry +` | behind/ahead | 本地=远端 tip | 落主干 commit |
|---|---|---|---|---|---|---|
| `docs/b7b2-main-verification` | #47 | merge | 0 | 1/0 | `409efc7` | `5d8f9916` |
| `docs/codeql-b7b-plan` | #44 | merge | 0 | 8/0 | `130d7ff` | `d3bee611` |
| `docs/codeql-b7c-acceptance` | #40 | merge | 0 | 64/0 | `759b4e4` | `d838aa36` |
| `docs/codeql-b7d-acceptance` | #43 | merge | 0 | 10/0 | `c6aa82d` | `facd65fc` |
| `fix/codeql-b7b2-rate-limit-bucket` | #46 | merge | 0 | 4/0 | `0bef447` | `76589c4f` |
| `fix/codeql-b7d-workflow-permissions` | #42 | merge | 0 | 12/0 | `6fb57d5` | `9ee00007` |
| `fix/codeql-batch7-real-fixes` | #38 | merge | 0 | 68/0 | `cab1eda` | `a6602201` |
| `fix/codeql-batch7c-path-shape` | #39 | merge | 0 | 66/0 | `0db4ed1` | `bb46dd3b` |
| `fix/codeql-b7b1-llm-cache-slot` | #45 | **squash** | **5** | 7/**5** | `40e74ec` | `85cd9bfe` |

前 8 条：`cherry +` = 0 且 `ahead` = 0 且 `merge-tree` 退出码 0 ⇒ **内容已在 `origin/main`**（§1 表第一类）。

第 9 条（#45，唯一一条 squash 入主干的）不能走计数判据，改用§5 的树 OID 直比：

```
$ git rev-parse "40e74ec^{tree}" "85cd9bfe^{tree}"
62fb9c1dfa03247dfb6b1fbfd49464dba0012b5a      # 分支 head
62fb9c1dfa03247dfb6b1fbfd49464dba0012b5a      # squash 提交 ⇒ 完全相同
$ git rev-parse --short "85cd9bfe^"           # squash 提交的父 = 分支 fork 点，上述判据适用
$ git diff --shortstat "85cd9bfe^..40e74ec"    # 5 files changed, 216 insertions(+), 35 deletions(-)
$ git show --stat --format="" 85cd9bfe | tail -1   # 5 files changed, 216 insertions(+), 35 deletions(-)
```

⇒ 两条独立判据（树 OID 全等 + 净差与 squash 提交逐项一致）互证：**#45 已完整并入**。它的 `cherry + = 5` / `ahead = 5` / `merge-tree` 退出码 `1` 全部是 squash 形态下的**预期假阳性**（§5 已记入该陷阱），不得拿它们当“未并入”证据。

处置结果（**已执行**，非将来时）：本文件入库（`108ee24`）并合入主干后，§6 那 9 条**本地 + 远端均已删**；连同本 PR 自身分支（`docs/branch-disposition-closeout`）共 10 条（该条成文时不可能包含自己，此处补记）。终态实测：本地 4 条（`main` / `v3` / `feat/isolation-hardening` / `test/rag-route-ablation-eval`），远端 6 条（上述四条 + `v2` + `origin/dependabot/uv/minor-and-patch-37a69dd668`）。§2 保留项与 §4 两条远端残余本轮未动。（原先本段写的是「本文件入库后…均删」的将来时，那是待执行承诺而非结果；现已执行并改为实测终态。）

## 7. 追加登记（2026-10-02）：并入 `feat/isolation-hardening` 时的两类新陷阱

> 场景：台账 §3 第一条的执行过程。它不是「删分支」而是「让分支真进去」，暴露了两个 §5 四条命令盖不到的判据盲区。

**陷阱一：auto-merge 不报冲突 ≠ 语义干净**。`git merge` 对 `.env.example` 自动合并不报错，但结果是 ADR-0007 的 12 个身份断言键**整块重复了两份**（主干 PR #41 登记过一份，来源分支 `d078312` 带的是同一块的早期副本）——两侧在不同行区域各加了自己的内容，三方合并看不出重叠。发现手段不是 `merge-tree` 而是**后置的领域不变量检查**：正则抽出全部 `^[A-Z0-9_]+=` 键名做 `Group-Object | Where Count -gt 1`。处置：先程序化确认两份 17 行区块逐字节全等，再删第二份；去重后 `git diff --cached HEAD -- .env.example` **为空**（等于还原主干版），59 个键零重复。⇒ 对配置/清单类文件（`.env.example`、白名单、路由表），合并后必须跑「重复项」不变量，而不能只看「无冲突」。

同类手法在本文档已有先例：§2 的 marker 计数用 `git grep -c`，本处用键名重复检测——都是把「看起来合干净了」翻译成可复跑的命令。

**陷阱二：「主干不采信 X」这类否定断言有时间戳**。主干 `docs/adr/0005` 当时写「不采信分支 `ff68aee` 的 T0 已落地声明，因为主干无 `execution.py`、grep 0 命中」——那句对当时为真。而本次并入**正好就是去落地 T0**，如果机械地「取主干侧」（因为它带来源标注、更权威），就会把一个已经作废的否定结论永久化。识别方式：读否定断言的**理由部分**（而非结论部分），判断本次变更是否正好抽掉了该理由。复验后取分支的 §6/§6.1，并保留主干的来源标注 + 加一段「状态转正的过程记录」（写明两次实测隔出一段真实差距）。配套防病：分支声明的每条产物（文件、能力位、导出、测试数）逐项 grep + 实跑后再写文书，不直接沿用**来源分支自带的结论**。
