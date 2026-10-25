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

## 5. 备选方案（为何不选）

- **合并 docs→feat**：无操作可做（祖先关系，fast-forward no-op）——"合并"在此语义上不成立，正确动作是删除；
- **机械 rebase PR #111 到 feat**：feat 已演化同一批文件（settings/recall 节点/001 DDL 均动过），冲突面大，且会把 docs 线形态强加给 feat；
- **保留双分支**：违背收敛目标，且两线各自演化同一批文件，后续每批都要双向对齐。
