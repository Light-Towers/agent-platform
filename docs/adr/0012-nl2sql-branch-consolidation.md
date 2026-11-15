# ADR-0012: nl2sql 多分支收敛为单分支 + 评审修复的三角验证重新落地

- 状态：**已决并执行完毕（2026-10-19 用户批准）**
- 日期：2026-10-19
- 来源：`docs/nl2sql-meta-lifecycle-review-2026-10-17` 合入前评审的后续分支治理动作
- 关联：`ADR-0011`（A 方案，feat 分支是其执行载体）

## 1. 现状与问题

收敛前远端 5 个 nl2sql 相关分支：`main`（nl2sql-service 旧版）/ `feat/nl2sql-meta-build-recovery`（135 commits vs main）/ `docs/nl2sql-meta-lifecycle-review-2026-10-17`（85 commits）/ `v3`（1 个独有 doc commit）/ 两个 fix 分支（PR #104 base=feat、PR #111 base=docs，分别指向不同 base）。

**实测血缘**：docs 整体是 feat 的祖先（6 个功能 commit + docs tip 全部经 `merge-base --is-ancestor` 证实）⇒ 零分叉、无冲突面。feat 独有的 50 个 commit = A 方案 Stage ①②③ 全线 + P0/P1/S/M 特性 + golden 22 条 + V3 残差 + 身份门/租户隔离。

## 2. 决策

保留 `feat/nl2sql-meta-build-recovery` 为**唯一** nl2sql 集成分支：

- docs 内容零损失包含于 feat ⇒ 不需合并（祖先关系，合并即 no-op），直接删；
- v3 的独有 commit（Phase 0 spec，220 行纯 doc）**cherry-pick 入 feat**（`0c35bf4`；删前验证文件与源**逐字节一致**，v3 其余 commit 皆在 main）；
- PR #104 直接合入 feat（squash `84897b4`）；
- **PR #111 不合入 docs**（那会让 docs 重新领先 feat，制造本次要消除的新分叉）——其 6 项修复经三角验证后**重新落地**为 PR #112（squash `2ecf93e`）。

## 3. 三角验证方法（本 ADR 的过程资产）

对每条评审修复，**先查目标分支现状再决定动作**，不机械 rebase（feat 已演化同一批文件，机械 rebase 会把 docs 线形态强加给 feat，如 7 槽位 vs 13 槽位）：

| 修复 | feat 现状（逐个实读） | 动作 |
|---|---|---|
| #105 env>YAML | **已修**（`348185e` 的 `_env_provided_fields()`：剔除 env/.env 已提供的字段，与 docs 线修法同机制同意图） | 不重复落地 |
| #106 召回降级 | 仍存在且**面更大**（feat 的别名主路是两个额外 meta 库裸调用） | 重新落地（防护 4 节点 + 超时 5s→15s） |
| #107 upsert | **已更优解决**（feat 有通用 `_upsert` + 返回 inserted/updated） | 不重复落地 |
| #108 render | 仍存在（`format_map(_SafeDict())` 原样） | 重新落地（槽位 7→13） |
| #109 filter_table | 仍存在（形态略异：`effective_query`、`llm_calls` 计数、无开关） | 重新落地（默认关=有意的行为回退） |
| #110 init 对账 | 仍存在（无锁无校验）；001 已被 `6e82ba2` 改过 | 重新落地（DDL 对着 feat 版重应用） |

**教训（不粉饰）**：评估阶段只读了 `get_settings` 主体、没读到 L287-292 的过滤行，曾误判 #105"仍存在"——**读全再判**；该误判在实施阶段阅读全量时被抓到，未造成重复落地。

## 4. 后果

- 远端终态 **main + feat 两分支**；feat 领先 main 138 commits（含 v3 spec 与两批修复）；
- #102-#110 全部关闭（#105/#107 的关闭评论注明 feat 早已修复的 commit 号）；
- **删除前安全核查救下两个本地分支（2026-10-19 登记）——2026-10-20 逐用例比对订正为"可退役"**：`feat/level1-durable-execution` 的 `b4428bf`（2026-08-21，Level 1 Durable Execution + 测试分层 level1/level2）当时为**全仓唯一副本**（不在 main/feat/v3/docs、无远端）⇒ 登记禁删、建议推远端备份。**订正（逐用例比对，非估计）**：其 7 个集成用例被 feat 现行套件**全覆盖**——lease 生命周期/release/stale → `tests/durability/test_pg_durability.py` 四测 + `tests/ha/test_lease_expiration`；checkpoint 落盘 + graph 字段 → 同文件 `test_crud`；G4 stale-owner fencing → `tests/ha/test_stale_writer`（断言更强：monotonic CAS + zombie 场景）；resume 跳过已完成节点 → `tests/ha/test_kill_after_checkpoint`（断言更强：副作用各 1 次）；并发接管唯一赢家 → `tests/ha/test_lease_contention`。其中 2 个用例依赖的 API（`PgExecutionOwnershipStore.claim_stale`、`PlannerRuntime.resume`）在 feat **已不存在**（分别被 V3 的 acquire-CAS + reaper、`ControlPlane.resume`/RecoveryOrchestrator 取代）——该测试文件拿到 feat 上直接 AttributeError ⇒ 血缘中间态，非缺失能力；其重写的 `test_pg_durability.py` 是 feat `tests/durability/` 版的**真子集**。⇒ **未推远端备份，本地分支退役删除**（内容零独有价值；commit 内唯一不在 feat 文档的信息——2026-08-21"Durable Execution 测试分 Level 1/2/3 层"决策——由本条目留痕：该决策实质已被 V3 HA 套件 + `requires_pg` marker 策略取代）。本地 `v2` 同步订正："138 个无远端独有 commit"为当时口径，现实测 `v2...feat` 独有 **0**（内容全在 feat）⇒ 一并删除；同批清理本地 `tb7/compose-e2e-smoke-closed`（独有 0）。**教训**："禁删/备份"类登记必须带复审触发条件（证据出现即主动复审），否则保守登记会供成死枝；
- 规则沉淀：① feat 线代码的修复一律走 PR 进 feat，**不进祖先/衍生 doc 分支**；② 本地不建名为 `feat` 的分支（与 level1 分支构成 D/F ref 冲突，曾造成半失败 checkout 污染索引）。
- **2026-10-27 只读分支体检（一条未删）**：9 条本地分支逐条实测（`git rev-list --count <b> ^HEAD` + `git cherry -v HEAD <b>`）。`feat/nl2sql-meta-build-recovery` vs HEAD 独有 **0**、vs main **169**——按 §2 它是保留的唯一集成分支，0 独有不构成死枝判据；`mirror/nl2sql-ttl-and-006-slim`（vs HEAD 6，含 1 个 merge）属公开镜像载体（AGENTS.md §4/§5），不计入「恒 2 分支」；其余 5 条 vs HEAD 独有数：`company-snapshot` 2 / `docs/dependabot-round4-2026-10-24` 2 / `fix/dependabot-pillow-13-2026-10-24` 3 / `fix/dependabot-security-int` 2 / `fix/dependabot-security-oct-2026-10-24` 2，且 `git cherry` **无一条**判为 patch 等价（全 `+`）⇒ 现有证据不足以证明内容已被 HEAD 覆盖，删分支又是破坏性动作（需用户批示），故**全部保留**。**方法告警**：`git cherry` 对 squash 合并天然失效（patch-id 不等价），「全 `+`」既不能证明独有、也不能证明已覆盖——判死枝必须树级比对（`git diff <b> HEAD -- <路径>` 或逐文件 blob 比对）。**复审触发条件**：任一分支经树级比对证实内容全在 HEAD，或用户明确批示处置。

- **2026-10-29 退役执行：`feat/nl2sql-meta-build-recovery` 已删（本地）**。触发 = 上一条的复审条件「用户明确批示处置」成立（用户原话：「删分支前，先将分支合并至当前分支，避免内容丢失」）。**先合并后删，合并实取为 no-op**：`git merge --no-edit feat/nl2sql-meta-build-recovery` → `Already up to date.`，HEAD 仍 `896f966e`、合并前后 `git status --short` 逐行相同（未提交改动未被触碰）。根因：该分支 tip `f6a6b9d8`（2026-10-23，累计 840 commits）**本就是当前工作线 `feat/nl2sql-ttl-and-006-slim` 的祖先**（`merge-base --is-ancestor` rc=0；`rev-list feat/nl2sql-ttl-and-006-slim..feat/nl2sql-meta-build-recovery` = 0）。⇒ 本条结论**不依赖 `git cherry`**（上一条已警告它对 squash 合并失效），只依赖 DAG 祖先关系 + merge no-op 两条，所认“内容零丢失”是可证的而非推断。
  - **角色转移（本条即《分支卫生》#1 要求的“确证退役结论”）**：§2 那句“唯一 nl2sql 集成分支”的角色已随工作移到 `feat/nl2sql-ttl-and-006-slim`；§2 原文不改（历史决策快照），以本条为准。
  - 删除先走 `git branch -d`，**它拒了**，原文理由：“not yet merged to `refs/remotes/github-legacy/feat/nl2sql-meta-build-recovery`, **even though it is merged to HEAD**” ⇒ 本轮查实一条可复用的 git 规则：**分支带 upstream 时，`-d` 校的是“已合入 upstream”，不是“已合入 HEAD”**，两者可以同时成立而 `-d` 仍拒。本例正是：本地 tip `f6a6b9d8` 领先镜像侧 tracking ref `a0e7b8ef`（`is-ancestor 本地→镜像侧` rc=1），但两侧内容**均全在当前线**（`is-ancestor 本地→HEAD` rc=0 且 merge no-op；`rev-list HEAD..镜像侧 tracking ref` = **0**）⇒ 删本地 ref 不丢任何提交。按《分支卫生》#1（“仅当已有 ADR/文档登记的确证退役结论时才用 `-D`”），本条即该结论 ⇒ 改用 `-D`。镜像侧 tracking ref 本身不在 `branch -D` 的触及范围内（它属 `refs/remotes/*`，只有 `fetch --prune` 或推远端会动）。
  - 远端面：它的 upstream 是 `github-legacy/feat/nl2sql-meta-build-recovery`（公开镜像侧同名分支），而 `git branch -r --contains` **无任何远端包含它** ⇒ `company` 侧本来就没有这条，删本地不碰远端；镜像侧那条按《分支卫生》#5 单列，本轮未取证（`ls-remote` rc=128）。
  - **复审触发条件**：① 若日后需该分支的历史形态，`f6a6b9d8` 仍是当前线祖先 ⇒ `git log f6a6b9d8` 直接可达，不需分支名；② 若发现某 commit 只存在于 `github-legacy` 那条 ⇒ 从镜像侧 fetch 回来重立分支名并推翻本条。

## 5. 备选方案（为何不选）

- **合并 docs→feat**：无操作可做（祖先关系，fast-forward no-op）——"合并"在此语义上不成立，正确动作是删除；
- **机械 rebase PR #111 到 feat**：feat 已演化同一批文件（settings/recall 节点/001 DDL 均动过），冲突面大，且会把 docs 线形态强加给 feat；
- **保留双分支**：违背收敛目标，且两线各自演化同一批文件，后续每批都要双向对齐。
