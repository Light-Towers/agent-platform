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

> 2026-10-02 终态指针：本表后两条（`feat/isolation-hardening`、`test/rag-route-ablation-eval`）已随 PR #49 / #50 入主干并**删除 ref**（本地+远端），`v3` 按当日拍板**保留**。删除动作的安全阀与可恢复性证明见 **§9.3**；本表保留为「当时为何不能删」的历史判据快照，不是现状。

| 分支 | tip | 相对基准（今日实测） | 为什么不能删 |
|------|-----|---------|-------------|
| `v3` | 26cd2fa（09-27） | **ahead 0 / behind 67** vs `main`（原记 ahead 47 / behind 19，**已失效**） | ⚠️ 原写的理由「主干尚未吸收」**错了**：PR #41（2026-10-01）已 `git merge origin/v3` 全量合入，且 `git merge-base --is-ancestor 26cd2fa origin/main` 退出码 0 ⇒ 内容零丢失风险。是否删 ref 不再是取证问题而是**组织决策**（长期集成分支名带里程碑语义，同 §4 `origin/v2` 的情形），建议先 `git tag archive/v3 origin/v3` 再删，**待拍板**。
| `feat/isolation-hardening` | d078312（09-28） | ahead 15 / behind 79 vs `main`（cherry 真独有 7 条）；相对 v3 曾为 ahead 15 / behind 12 | ~~不是债~~ → **已处置**：真独有 7 条（ADR-0005 T0 内核协议下沉 + 2 个 kernel 测试 + audit 真库修复 + testing-playbook + lint/uv.lock 收尾）已随 `feat/execution-memory-kernel-onto-main` 入主干（对主干净差 **+411/−23 / 11 文件**，非原记 vs v3 的 +842/−46）。PR #18 仍 CLOSED 未合，其 base `v3` 已不再是合理目标。 |
| `test/rag-route-ablation-eval` | 4cffe7c（09-30） | ahead 25 / behind 82 vs `main`（2026-10-02 重测，原记 75/19 是 10-01 的 main tip）；cherry 真独有 **25 / 等价 0** | ~~唯一持有者~~ → **已处置**：25 条全为真独有（与 isolation 那条的 8/7 分布相反），已整支 `git merge` 入主干（对主干净差 **87 files / +10752 / −435**）。「从未开过 PR」在本批被证实为风险而非收益，见 §7 陷阱三。 |

`test/rag-route-ablation-eval` 的唯一性取证（`git grep -c <marker> <ref>` 命中文件数）：

| marker | main | v3 | 该分支 | 含义 |
|--------|------|----|--------|------|
| `shutdown_tracing` | 0 | 0 | **7** | tracing 生命周期 shutdown 接线只在它身上 |
| `agent_runtime.otel` | 10 | 10 | 11 | 门面退役（`e086483`）未进主干，主干仍是旧门面 |
| `build_api_app` | 12 | 12 | **18** | 工厂装配站点更多（ks 迁 `build_api_app` + lint 白名单摘除，`b3c5c97`） |
| `RAGAS` | 1 | 1 | **7** | RAGAS adapter 接线 + 126 容器实跑（`4278e23`） |
| `ablation` | 12 | 11 | **25** | RAG 路别消融评测主体 |

> **本表是「2026-10-01 当时为何不能删」的历史取证，不是现状**：2026-10-02 该分支整支入主干后，五行 marker 的 `main` 列计数全部上移（尤其 `agent_runtime.otel` 行——门面退役正是本批带进去的，「主干仍是旧门面」这句已作废）。

## 3. 处置路径（2026-10-02 更新：三条均已定案——前两条已**合入主干**，第三条被现实关闭）

- ~~`feat/isolation-hardening` → 先解冲突再开 PR（base `v3`）~~ → **已执行，且 base 改为 `main`**（原写「唯一冲突文件 `scripts/audit_tenant_access.py`」只对 v3 成立；对 main 实为 **4 个文件**，多出的三个正是 PR #41 合流时手工处理过的那批：`knowledge_service/main.py`、`docs/adr/0005`、`plan-memory-hardening`）。取侧逐条记录在并入提交 `f666bc8` 的正文，及本文件 **§7**。
- ~~`test/rag-route-ablation-eval` → 拆分成小 PR 进 `main`~~ → **已执行并已合入主干**（2026-10-02，分支 `feat/observability-eval-onto-main` → **PR #50 已 merge**，主干新 tip `617cbf2`@10:36:37Z；合入终态与 CodeQL 复验见 **§8**）。不拆的理由是取证不支持它的前提：原写「75 个独有提交……很可能同样已大面积入主干」，实测 `git cherry -v origin/main test/rag-route-ablation-eval` = **25 `+` / 0 `-`**（全部真独有，无一已等价入库），拆分只能减少「评审面」而不能减少「内容量」；而两条主题链（观测全局装配 / RAG 分层评测）在分支上本就交织在同一批文件（`agent_core/tracing.py` 既被观测链重写又被 `--extra otel` 评测链消费），拆开各开一个 PR 会引入「先合的那半跑不过门禁」的中间态。沿用 PR #41 先例：`git merge --no-commit --no-ff` 全量、不 cherry-pick、不用 `-X ours/theirs`。
  原写「lint 白名单需按现状重写」经实跑证伪为**无需重写**：合并版 lint（13 条门禁）在主干现状上 rc=0，`_FASTAPI_WHITELIST` 摘除 ks 也成立（本批同时带来 ks 迁 `build_api_app`）。真出问题的是分支自带的一个环境依赖型用例，见 §7 陷阱三。
- ~~`v3` → 与主干的合流是独立议题（47 commits）~~ → **已被现实关闭**：PR #41（2026-10-01）就是那次合流（`git merge origin/v3` 全量、不 cherry-pick、不用 `-X ours/theirs`），今天实测 v3 对 main ahead = 0。剩下的只是 §2 那条「是否删 `v3` ref」的组织决策。

## 4. 远端残余（需人工拍板，本轮未动）

> 2026-10-02 订正：第二条所列 `origin/dependabot/uv/minor-and-patch-37a69dd668`（PR #26）**已不存在**——该 PR 关闭后 ref 被 `git fetch --prune` 回收，属历史快照。今天的远端 dependabot 残余是两支：`pypdf-6.19.0`（PR #51，已并入主干）与 `minor-and-patch-7e9aec2f8c`（PR #52，OPEN、对主干净独有 1 条 ⇒ 活分支勿删），逐条定性见 **§9.5**。

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

## 7. 追加登记（2026-10-02）：并入过程中暴露的四类判据盲区

> 场景：台账 §3 前两条的执行过程。它们不是「删分支」而是「让分支真进去」，暴露了 §5 四条命令盖不到的判据盲区（陷阱一/二来自 isolation 并入，陷阱三/四来自 ablation 并入）。

**陷阱一：auto-merge 不报冲突 ≠ 语义干净**。`git merge` 对 `.env.example` 自动合并不报错，但结果是 ADR-0007 的 12 个身份断言键**整块重复了两份**（主干 PR #41 登记过一份，来源分支 `d078312` 带的是同一块的早期副本）——两侧在不同行区域各加了自己的内容，三方合并看不出重叠。发现手段不是 `merge-tree` 而是**后置的领域不变量检查**：正则抽出全部 `^[A-Z0-9_]+=` 键名做 `Group-Object | Where Count -gt 1`。处置：先程序化确认两份 17 行区块逐字节全等，再删第二份；去重后 `git diff --cached HEAD -- .env.example` **为空**（等于还原主干版），59 个键零重复。⇒ 对配置/清单类文件（`.env.example`、白名单、路由表），合并后必须跑「重复项」不变量，而不能只看「无冲突」。

同类手法在本文档已有先例：§2 的 marker 计数用 `git grep -c`，本处用键名重复检测——都是把「看起来合干净了」翻译成可复跑的命令。

合并后对**全部 35 个被修改（`--diff-filter=M`）的 `.py`/`.toml`** 跑了一遍同族不变量（顶层 `def`/`class` 名重复计数 + `tomllib` 解析）：零命中（全部 parse 通过、无重名）。但同族的另一种形状确实出现了，见下面的陷阱四。

**陷阱二：「主干不采信 X」这类否定断言有时间戳**。主干 `docs/adr/0005` 当时写「不采信分支 `ff68aee` 的『T0 已落地』声明，因为主干无 `execution.py`、grep 0 命中」——那句对当时为真。而本次并入**正好就是去落地 T0**，如果机械地「取主干侧」（因为它带来源标注、更权威），就会把一个已经作废的否定结论永久化。识别方式：读否定断言的**理由部分**（而非结论部分），判断本次变更是否正好抽掉了该理由。复验后取分支的 §6/§6.1，并保留主干的来源标注 + 加一段「状态转正的过程记录」（写明两次实测隔出一段真实差距）。配套防范：分支声明的每条产物（文件、能力位、导出、测试数）逐项 grep + 实跑后再写文书，不直接沿用**来源分支自带的结论**。

**陷阱三（ablation 并入）：「从未开过 PR」的分支，它的测试只在作者本地环境成立过**。`packages/agent-core/tests/test_tracing_degradation.py`（分支新增）里 `test_init_enabled_without_endpoint_degraded` 断言 `reason == "no_export_endpoint"`，而同文件另外两条环境敏感用例**都挂了 `@pytest.mark.skipif(_SDK_AVAILABLE)`**——唯独这条没挂。而 kernel 的降级原因判定是「依赖层先于配置层」（`tracing.py` 的 `if enabled and not _SDK_AVAILABLE` 在 `elif enabled and not can_export` 之前），所以不装 OTel SDK 的宿主上该用例必红。**默认 CI 恰好不装**（`make ci` → `make test` 根 session 无 `--extra otel`，只有末行单独那个 session 装）⇒ 分支作者本地装了 SDK，全绿；这条分支入主干后首次进 CI 即红。处置：不是改断言也不是删用例，而是**把隐含前置条件显式化**（该用例 `monkeypatch.setattr(kernel_tracing, "_SDK_AVAILABLE", True)`，早退分支不构造 provider，不需真 SDK），并**新增**一条 `skipif(_SDK_AVAILABLE)` 用例钉住「同时缺 SDK + 缺端点时先报 `sdk_not_installed`」的优先级——两条合起来把 2×2 在任一宿主都钉完整（实跑：无 SDK 环境 11 passed；`--extra otel` 环境 23 passed / 3 skipped）。⇒ 可复跑判据：并入无 PR 历史的分支前，先问「它绿过 CI 吗」；没绿过就把 **CI 环境**（不是本地环境）的 `make test` 全 session 当验收线，并特别盯那些“同文件邻居都有 guard、就它没有”的不对称。

**陷阱四（ablation 并入）：auto-merge 不报冲突的另一种形状——Python 注册表里同名变量被两侧装不同门禁**。`scripts/lint_architecture.py` 的 `main()` 内，主干用局部变量 `v6..v9` 装 P8/P9/P10/P11，分支用**同名** `v6..v9` 装 L-3/L-1/L-2/L-4。合并后代码语法完全合法、ruff 不报、`import` 不报，但“后者覆盖前者”会让四条门禁静默失效——它不是重复定义（故上面那套顶层 `def` 重复不变量抓不到），而是同名赋值的控制流语义。另外分支侧的 registry 还带着收敛前的旧标签（「批 3 架构约束」/「C1 回归面约束」，主干已改号 P9/P10）。处置：以主干 `main()` 为基底（保留 P 编号与标签），分支四条门禁改用 `v10..v13` 追加；同名但两侧逐字一致的 7 个函数体保留一份；分支独有的 L-1〜L-4 常量/函数整段追加；`_iter_prod_py` 改为复用主干已有的 `_skipped_rel`（避免两套排除面各写一遍）。⇒ 对「注册表/累加器」类函数（一堆同名局部变量 + 末尾统一返回），合并后必须通读整个函数体，不能只看冲突标记。另附一条「门禁全绿不等于门禁有效」的防范：本次 13 条门禁 rc=0，额外用一棵伪造目录树做**负对照**（写入 `cm.__enter__()` / `app.state.tracer` / `init_tracing()` 三行），确认 L-1/L-2/L-3 真的各自报违规后才定案（合并后的 `_iter_prod_py` 扫到 515 个生产 `.py`）。

## 8. 追加登记（2026-10-02）：PR #50 合入终态、主干 CodeQL 复验、5 条 ref 的并入取证

> 场景：§3 第二条的收尾。`feat/observability-eval-onto-main` 开 **PR #50**，2026-10-02T10:36:37Z 以 **merge commit**（非 squash）合入，主干新 tip `617cbf2`，双亲 `b7448c1` + `afc738a`。取证脚本：`.codeartsdoer/temp/verify_main_rescan_50.py`（逐判据输出 `=== 总体：PASS ===`）与 `.codeartsdoer/temp/refs_evidence_vs_main.py`（只读，不删任何 ref）。

**合入内容零漂移（用 §5 的最强判据，而非 diffstat 巧合）**：`git rev-parse "afc738a^{tree}" "617cbf2^{tree}"` 两个树 OID **全等**（`05974143…`）⇒ GitHub 那次 merge 未引入 PR 之外的任何内容。对上一 tip 的完整净差 `git diff --stat b7448c1..617cbf2` = **89 files / +10779 / −441**（= merge 提交自身的 87 files / +10752 / −435，再加台账 + CHANGELOG 两份文档回写）。

**主干 CodeQL 告警面复验（PR 绿 ≠ 主干绿，全部在 `refs/heads/main` 实取）**：

| 判据 | 实测 |
|---|---|
| `ref=refs/heads/main` 的 open | 恰 `#38` / `#39`（`py/weak-sensitive-data-hashing`） |
| 位置 | `guardrails/auth.py:103` col 47-69（`fingerprint()` 的 hmac-sha256）/ `:128` col 29-60（`legacy_thread_id()` 的 `sha256[:12]`）。**不是**旧文档里的 `:92`/`:117`：位移 +11 由 PR #49 那批给 `auth.py` 加 docstring 造成（`c514f0f`，已实测为 `b7448c1` 的祖先），而本批 `git diff b7448c1..617cbf2 -- …/guardrails/auth.py` **为空** ⇒ 与本批无因果，只说明旧行号基线已过期 |
| 重扫是否真发生在新 tip | 两条告警的 `most_recent_instance.commit_sha` 均 = `617cbf29…`；`code-scanning/analyses` 最新两条 created = `10:37:53Z` / `10:37:18Z`（python + actions），ref=`refs/heads/main`、commit=`617cbf29`，晚于合入时刻 10:36:37Z |
| 存量与号段 | `fixed` 44 / `open` 2 / **`dismissed` 0**；全仓最大告警号 **48** 不增；`created_at > 10:36:37Z` 的告警 **0** 条 |
| 主干门禁 | check-runs `ci` / `ha` / `assembly` / `Analyze (python)` / `Analyze (actions)` 均 completed/success（`ci` success 即在 `617cbf2` 上真跑过 `make ci`） |
| 本机快验（同一 tip） | `ruff check .` passed · `lint_architecture.py` **13 条全 rc=0** · `check_doc_sync.py` 0 警告 · `eval` 15/15 = 100% |

**5 条 ref 的并入取证（统一以 `origin/main` 为基准，消除 §1 的 base 陷阱；`cherry -v` 列的是输出行数，tip 已全量入主干时该命令输出为空）**：

| ref | tip | `cherry -v origin/main` | beh/ahead | `merge-tree` | tip 是 `origin/main` 祖先 | 本地=远端 | 引入它的主干 merge（tip 为其父） |
|---|---|---|---|---|---|---|---|
| `test/rag-route-ablation-eval` | `4cffe7c` | 0 行 | 85/0 | 0 | **是** | 是 | `6ee7283`（经 PR #50） |
| `feat/isolation-hardening` | `d078312` | 0 行 | 110/0 | 0 | **是** | 是 | `f666bc8`（经中间分支 → PR #49） |
| `feat/execution-memory-kernel-onto-main` | `f459693` | 0 行 | 29/0 | 0 | **是** | 是 | `b7448c1` = PR #49 的 merge commit |
| `feat/observability-eval-onto-main` | `afc738a` | 0 行 | 1/0 | 0 | **是** | 是 | `617cbf2` = PR #50 的 merge commit |
| `v3` | `26cd2fa` | 0 行 | 113/0 | 0 | **是** | 是 | `889d417`（第二父恰为 `26cd2fa`） |

⇒ 五条在**内容层面**都零丢失风险。但「取证充分」不等于「可删」：`v3` / `v2` 带里程碑语义（CHANGELOG 有跨版本交叉引用），处置建议仍是先 `git tag archive/<name>` 再删分支，**待拍板**（见 §2 / §4）。

**陷阱五（本轮新增）：「该分支的 PR 是否 MERGED」不能当并入判据**。三条实测形状都会把判定带偏：

1. `feat/isolation-hardening` 自己的 **PR #18 至今 CLOSED 未合**，但它的 7 条真独有提交是随中间分支 `feat/execution-memory-kernel-onto-main`（PR #49）进的——「分支没有已合并的 PR」在这里是**搬运路径的形状**，不是未并入的证据。
2. `v3` 用 `gh pr list --head v3` **查不到任何 PR**（PR #41 的 head 是 `integration/v3-into-main`，不是 `v3`），按「有没有对应 PR」判会直接无从判定。
3. REST `GET /pulls/{n}` 的 `state` 只有 `open`/`closed` 两值，**已合并的 PR 也返回 `closed`**（PR #41 即如此，`merged_at=2026-10-01T13:00:43Z` 才是 merged 信号）；要拿 `state=MERGED` 必须走 GraphQL（`gh pr list --json state` 已是 GraphQL）。

⇒ 删 ref 的判据只认**内容侧**：`git merge-base --is-ancestor <tip> origin/main` 退出码 0 **且** `git cherry -v origin/main <tip>` 无 `+` 行；PR 元数据只用来解释「怎么进去的」，不用来判「进去没有」。（本轮第一版取证脚本正是按「PR 非 MERGED ⇒ 不许删」写，对上面三条全部误判，已换成祖先判据。）

**另记一条已登记过的坑再次踩到（不新增判据，只说明为何要写进脚本注释）**：`most_recent_instance.location` 是扁平 `{path,start_line,start_column}` 而非 SARIF 的 `physicalLocation.uri`，`check-suites` 的 `name` 恒为 `null`——这两处早先已在 CHANGELOG（B7d / B7b-2 段）登记并修过，但沿用的旧骨架 `verify_main_rescan_v3.py` 仍是错形状，本轮复用它时：location 取到 `?` ⇒ 「行号未漂移」这条判据**在旧脚本里其实一直在空转**（取值失败却被当成通过），check-suites 分支则直接 `KeyError` 崩掉。⇒ 防范：**判据取不到值必须 fail-closed**（缺失即 FAIL，不许 `dict.get(..., "?")` 兜底后继续比较），且旧脚本复用前先拿一条已知答案的告警做正对照。

## 9. 追加登记（2026-10-02）：4 条 ref 删除终态、门禁预期集订正、依赖安全告警闭合、剩余项定性

### 9.1 PR #53（纯文档收尾）合入终态

`docs/pr50-merge-closeout` @ `a98f0fa` → **PR #53**：5 条 checks 全 pass（`ci` push 2m56s / pull_request 3m9s、`Analyze (python)` 52s、`Analyze (actions)` 35s、`CodeQL` 2s），`mergeable=MERGEABLE` 且 `mergeStateStatus=CLEAN`，2026-10-02T11:06:58Z 以 merge commit 合入 ⇒ 主干新 tip `63a8f23`（双亲 `617cbf2` + `a98f0fa`）。零漂移沿用 §5 的树 OID 直比：`git rev-parse "a98f0fa^{tree}" "63a8f23^{tree}"` 全等（`aacee653…`），对上一 tip 净差 `4 files / +315 / −4`（即本提交自身，GitHub 未掺入 PR 外内容）。

主干复验（`.codeartsdoer/temp/verify_main_rescan_53b.py` → `=== 总体：PASS ===`）：open 仍恰 `#38`/`#39`（`auth.py:103` / `:128`，本批未碰源码故不漂）、两条实例 `most_recent_instance.commit_sha` = `63a8f239…`、`fixed` 44 / `dismissed` **0** / max **48** / `created_at > 11:06:58Z` 新建 **0**、analyses 两条落在新 tip（11:07:36Z / 11:08:14Z）。

### 9.2 陷阱六：「主干应有的门禁集合」不能写成常量，必须按本批 changed paths 派生

第一版（`verify_main_rescan_53.py`）沿用 §8 那张表的常量集 `{ci, ha, assembly, Analyze×2}`，对本批报 FAIL：`ha` / `assembly` 两条 check-run 在 `63a8f23` 上根本不存在。**不是漏跑，是 `paths:` 过滤**：`.github/workflows/ha.yml` 与 `ha-assembly.yml` 的 `push:` 都带白名单，二者均不含 `docs/**`，而本批 4 个文件全在 `docs/` 与根 `*.md`。交叉验证（不是推断）：`actions/workflows/{ha,ha-assembly}.yml/runs?head_sha=63a8f23` 均 `total_count=0`，而 `head_sha=617cbf2`（含代码改动）各为 1。

⇒ 修订后的判据两条：① 预期集 = `{ci, Analyze (python), Analyze (actions)}` ∪ 按 `git diff --name-only <prev> <tip>` 对两组 `paths:` 求交命中的 `ha` / `assembly`；② **被过滤掉的门禁必须再用 workflow-runs API 证明确实 0 run**，否则会把「未触发」与「触发了但没挂上 check-run」两种相反的形状混为一谈。正向镜像用例已坐实：PR #51 只动 `pyproject.toml` / `applications/agent_federation/pyproject.toml` / `uv.lock`，两个过滤器同时命中 ⇒ 预期集自动变 5 条，实跑 5 条齐（9.4）。

与 §8 末段那条（API 字段形状取错）同族但不同层：**这里错的是「判据的应有集合」本身，它是环境输入的函数**，写死即双向风险（假阳性白修 / 假阴性漏拦）。另注：`ci` 白名单里含 `docs/**`，故文档批次仍有 `make ci` 真跑兜底（push + pull_request 双事件），只是重型基础设施门禁按设计不参与。

### 9.3 4 条 ref 的删除执行终态（`.codeartsdoer/temp/delete_merged_refs.py`）

用户 2026-10-02 拍板范围为「只删 4 条已并完的 feature/test 分支」（`v3` / `v2` 带里程碑语义保留）。执行前脚本内再做四重安全阀（全 fail-closed，任一不满足则整批不删并 `exit 1`）：祖先 / `cherry` 无 `+` / 本地 tip == 远端 tip == 预期 tip / 白名单外 ref 一律不碰。

| ref | tip | ancestor | `cherry +` | local | remote | 删除回显 |
|---|---|---|---|---|---|---|
| `test/rag-route-ablation-eval` | `4cffe7c` | YES | 0 | =预期 | =预期 | `- [deleted]` + `Deleted branch (was 4cffe7c)` |
| `feat/isolation-hardening` | `d078312` | YES | 0 | =预期 | =预期 | 同上 |
| `feat/execution-memory-kernel-onto-main` | `f459693` | YES | 0 | =预期 | =预期 | 同上 |
| `feat/observability-eval-onto-main` | `afc738a` | YES | 0 | =预期 | =预期 | 同上 |

执行：`git push origin --delete <4>` rc=0（远端回显 4 行 `- [deleted]`）、`git branch -d <4>` 四条 rc=0（用 `-d` 而非 `-D`：未并入者 git 自拒，等于第二道免费安全阀）。删后复查：本地剩 `docs/pr50-merge-closeout` / `main` / `v3`；远端剩 `main` / `v2` / `v3` / `docs/pr50-merge-closeout` / 两条 dependabot。

**可恢复性证明（删 ref 不等于删内容）**：四个 tip 删后仍 `git merge-base --is-ancestor <tip> origin/main` = True ⇒ 对象由主干历史持有，`git branch <name> <sha>` 可原位重建。这条证明是「先落账再删」能成立的根：台账 §8 的取证表已进主干，所以删除动作自身可审计、可逆。

### 9.4 依赖安全告警：主干默认分支 8 条 high 已闭合，另 1 组依赖 PR 被本仓 L-4 拦下

发现路径本身是个盲区信号：这 8 条**不是本仓任何门禁报的**，而是 `git push --delete` 时远端回显带出的（`GitHub found 8 vulnerabilities … (8 high)`）。⇒ 仓内 CI 只看 CodeQL，不消费 Dependabot alerts，这类信号只能靠人工看到回显（已入 `docs/TODO.md` §8）。

取证（`.codeartsdoer/temp/dependabot_inventory.py`）：8 条全为**同一个包** `pypdf`（pip / `relationship=direct` / manifest=`uv.lock`），全是解析不可信输入时的资源耗尽类（内存/长运行时），首补版本递增至 **6.19.0**；消费面确认为真·攻击者可控输入：`applications/agent_server/api/import_router.py:59` 与 `applications/agent_federation/tools/upload_file_read_tool.py:16` 都在解析上传文件时 `PdfReader(...)`。声明处两处：根 `pyproject.toml:32`（`pdf` extra）与 `applications/agent_federation/pyproject.toml:56`（`docs` extra）。

处置（用户拍板「现在合入」）：**PR #51**（`pypdf 6.16.1 → 6.19.0`）合入前按交接门禁先跑一次 L3 深度审查，并且**先 `gh pr checkout 51` 把待审提交纳入本地基座**（否则审的不是我即将合入的代码，「无发现」就是空转）⇒ findings = 0。2026-10-02T11:28:03Z 合入，主干新 tip `baa965f`（双亲 `63a8f23` + `d3cf899`）。

主干验收（`.codeartsdoer/temp/verify_main_pypdf_51.py` → `=== 总体：PASS ===`）：

| 判据 | 实测 |
|---|---|
| Dependabot `state=open` | **0**（合入前 8） |
| 闭合方式（强证据） | 8 条均 `state=fixed` 且 `dismissal_data=null` ⇒ 重扫判定消失，**未走 dismiss 通道**；`updated_at` 集中 `11:29:11Z–11:29:14Z`（合入后 68–71 秒） |
| CodeQL 告警面 | 本批零源码改动，复验仍 open 恰 `#38`/`#39`、实例 sha = `baa965f7…`、`fixed` 44 / `dismissed` 0 / max 48 / 新建 0 |
| 主干门禁（派生集 5 条） | `ci` / `ha` / `assembly` / `Analyze (python)` / `Analyze (actions)` 均 completed/success |

又一条 API 形状伪影（同属「取不到值必须 fail-closed」族）：Dependabot 告警的 REST 列表**没有 `closed_at` 字段**（那是 GraphQL 的），且 `state` 的终态枚举是 **`fixed` / `dismissed`，不存在 `closed`** —— 第一版按 `state != "closed"` 断言，把 8 条正确的 `state=fixed` 全判为异常（幸好是假阴性方向，没造成误报成功）。

**PR #52**（minor-and-patch 组 14 项，改 9 个 pyproject + lock）的 `ci` **失败，按拍板保持 open 不动**。根因是本仓 **L-4 架构门禁如实拦截**（非环境抖动，日志已取）：它把根 `pyproject.toml` 的 `opentelemetry-api` 抬到 `>=1.45.0`，而 `packages/agent-core/pyproject.toml` 仍是 `>=1.24`（主干当前两处均 `>=1.24`，一致），L-4 要求多处下界一致以防组合解析回溯 ⇒ 后续动作是「按 `plan-observability §3.3` 归一下界」，属独立决策面（已入 `docs/TODO.md`）。

### 9.5 剩余 ref 与待办的逐条定性（本轮明确不动的部分）

> 表内不写 `behind` 绝对数：它每合一个主干提交就变，不具可复现性；定性只依赖不变量（ahead = 0 / `cherry` 无 `+` / 是 `origin/main` 祖先）。

| 项 | 实测形状 | 定性与处置 |
|---|---|---|
| `v3` @ `26cd2fa` | `cherry -v origin/main` 0 行、ahead 0、本地=远端 | 内容零丢失风险，**删不删是组织决策不是取证问题**。2026-10-02 拍板：本轮**保留**（`archive/v3` tag 方案未采纳也未否决） |
| `origin/v2` @ `b691ff1` | 同上；**本地无此分支**（`rev-parse v2` = `Needed a single revision`） | 同 `v3`，带里程碑语义，**保留**；本地无需动作 |
| `dependabot/uv/pypdf-6.19.0` @ `d3cf899` | 已随 PR #51 入主干 ⇒ 现为「已并完」 | 收尾登记后即可删（不阻塞主干验收） |
| `dependabot/uv/minor-and-patch-7e9aec2f8c` @ `4aa4233` | `is-ancestor` = **NO**、`cherry +` = 1、PR #52 OPEN | **活分支，勿删**（且其 ci 红，见 9.4） |
| B7b-4（`#38`/`#39` 真修） | 前置取证仍卡 `192.168.100.126`：banner 交换前被关闭，累计 5 次同签名 ⇒ 本轮**未再硬连**（沿用已入库结论，不拿旧结论冒充新实跑） | **不可开工**，属外部条件依赖非代码缺口 |
| R19（issue #23） | 未动工；`FastAPI(telemetry=…)` 关闭项 + 新 lint 门禁均未实现 | 需先按红线出方案，并做真集群端到端复验（同样卡部署侧环境） |
| `plan-multi-expert-adjudication-2026-09-30.md` | 已随 PR #53 入库（269 行，状态 Proposed） | 本轮不实施；其三个基座提交已在主干 |

