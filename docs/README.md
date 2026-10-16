# docs 索引 · 哪篇作数、哪篇只是历史

> 本文件由 2026-10-15 的文档治理生成：**未删除、未移动任何文档**，只做分层与状态登记。
> 现状：`docs/` 141 个文件 / 约 2.6 MB；其中 `docs/plans/` 72 个文件 = 71 篇 md + 1 份配套盘点件 `p0-4-blind-except-inventory.txt`。71 篇 md 里按 §6 的口径命令实测 **42 篇有可辨状态行、29 篇未命中**（名单见 §7；该口径有已知漏计，29 是上界）。

## 1. 三条判据（先读这个，别先翻目录）

1. **文件名带日期 ⇒ 它是当日快照，不是活文档**。仓库既有纪律：dated 证据文件留档、不外引。要改结论请改不带日期的那篇，然后让快照保持原样。
2. **一篇 plan 是否还活着，只看三件事**：① 被 AGENTS.md / ARCHITECTURE.md / README.md 点名（下表标 ★）；② 文内状态行写着「待拍板 / Proposed / 实现中」；③ `docs/TODO.md` 里有对应条目。三者皆无 ⇒ 视为已了结，不必读正文。
3. **状态只有两种可信来源**：文内自述（下表「自述状态」列即原文摘录），或本轮补写且附依据。标「未标」的篇目**含义是我还没读过正文**，不许从文件名推断它做了什么。

## 2. 活文档层（无日期后缀，可当现值引用）

| 文件 | 作用 | 提及 |
|---|---|---|
| `docs/TODO.md` | 排期台账（判「会不会修」的唯一面） | 98 |
| `docs/architecture/agent-harness-capability-map.md` | 能力现状地图（管「现在有没有」） | 4 ★ |
| `docs/architecture/architecture-improvement-plan.md` | 优化项 A~H + 技术债登记 TB-* + §0.1 内核契约 | 20 ★ |
| `docs/architecture/architecture-boundary-app-vs-agent-federation.md` | 双轨职责边界 | 12 ★ |
| `docs/adr/0005-execution-memory-kernel-contract.md` | 执行/记忆内核契约 | 5 ★ |
| `docs/adr/0006-isolation-dimension-contract.md` | 隔离维度契约 | 5 ★ |
| `docs/adr/0007-server-asserted-tenant-identity.md` | 服务端断言租户 | 7 ★ |
| `docs/adr/0008-auth-mode-selection.md`、`docs/adr/0009-vector-store-selection.md`、`docs/adr/0010-ui-stack-selection.md` | **roadmap #24 三项悬置选型的决策记录**（认证方式 / 两套向量存储 / 界面）。三篇状态都是**未决**：内含已决边界、选项代价、否决理由、重启条件，以及各一行「待用户回答」⇒ 引用时不得当作已定选型 | 0（2026-10-16 新建；由 `docs/plans/plan-production-delivery-roadmap-2026-10-09.md` #24 与 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §13 指向） |
| `docs/operations/testing-playbook.md` | 分层验证与实跑配方 | 29 ★ |
| `docs/operations/env-126-inventory.md` | 内网三机部署态基线（读数绑 rev） | 14 ★ |
| `docs/operations/minimal-release-runbook.md` | 上台手册（含「这是多 agent 吗」标准答法 §11） | 11 ★ |
| `docs/operations/observability-pitfalls.md` | 观测面坑档 | 5 ★ |
| `docs/operations/demo-questions.md` | 演示问答口径 | 5 |
| `docs/plans/plan-f-single-runtime-multi-planner.md` | Plan-F 演进总纲（AGENTS.md 顶部指向） | 13 ★ |
| `docs/plans/production-delivery-anchor-map-2026-10-09.md` | 交付锚点取证（带日期但被活文档点名，见 §4 注） | 7 ★ |
| `docs/plans/skill-consolidation-inventory.md` | Skill 收敛盘点 | 3 ★ |
| `docs/plans/tech-debt-multi-agent-2026-09-23.md` | 多 Agent 技术债 | 3 ★ |
| `docs/project-introduction-2026-10-12.md` | **对外唯一交付稿**（讲解用，禁词见文内纪律） | 1 |
| `docs/runtime-self-build-analysis.md` + `docs/opensource-runtime-counterparts.md` | 业界对照族（框架层 / 内核原语层） | 4 / 0 |
| `docs/runtime-analysis-overview.md` | **已并入** `runtime-self-build-analysis.md`（2026-10-15 合并 A），本页仅作旧链接寻址 | 0 |
| `docs/adr/0003`~`0004` | 早期 ADR，`0004` 状态仍为「修订中」 | 0 / 3 |

未入库、只在本机存在的一篇：docs/agno-agentos-comparison.md（平台层竞品对比，未提交，clone 后不存在，故按 AGENTS.md 防漂移规矩不以反引号路径书写）。

## 3. `docs/plans/` 71 篇 md 分层（按主题簇）

「自述状态」= 文内状态行摘录；「未标」= 文内没有可辨状态行，**需读正文才能定**。提及数为全仓入库文件中该文件名的出现次数（含 CHANGELOG 历史条目与自身提及），只作相对热度，不作"仍在用"的证据。

> **2026-10-16 追记（本层新增 4 行，其余行未动）**：本节写就时是 71 篇，现值为**顶层 `docs/plans/*.md` 入库 75 篇 / 文件系统 76 篇**（差的 1 篇是并行会话新建、此刻尚未入库的 plan-deep-research-app-2026-10-16.md——**按 AGENTS.md「不入库路径不用反引号」的纪律这里写成普通文本**，且**本索引不代登**，由它自己的会话登记）。复取命令：`git ls-files docs/plans | grep -cE '^docs/plans/[^/]+\.md$'`。新登记的四篇：`plan-v3-unwired-landing-2026-10-15`、`plan-unfinished-completion-schedule-2026-10-16`、`plan-identity-gate-6of6-2026-10-16`、`plan-forensic-provenance-wiring-2026-10-16`。
> **两条没有重取、不得当现值引**：① 顶部第 4 行的「42 篇有状态行 / 29 篇未命中」与 §7 名单仍是 2026-10-15 快照（上面四篇都**有**可辨状态行，但按 §6 口径命令未重跑）；② 四行的「提及」数在本批合入后会各自 +1 以上（新行本身就是新增引用），复现请用 `git grep -c -o -- "<文件名>" | awk -F: '{s+=$NF} END{print s}'` 现取。

### 3.1 安全与依赖整改（CodeQL / Dependabot / 风险接受）

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-codeql-codescanning-remediation-2026-10-01.md` | 未标 | 10-01 | 7 |
| `plan-codeql-batch6-kernel-sanitizer-models-2026-10-01.md` | 已执行并已验收（PR #36 合入 = `0bc5175`） | 10-01 | 4 |
| `plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` | B7a 已执行（#42 位移重开） | 10-01 | 9 ★ |
| `plan-codeql-b7b-principal-thread-identity-2026-10-01.md` | 取证完成、三项已拍板 ⇒ 可开工 B7b-1 | 10-04 | 11 |
| `plan-dependabot-21-alerts-closure-2026-09-30.md` | 未标 | 10-01 | 3 |
| `dep-security-accepted-risks-2026-09-25.md` | 未标（性质：已接受风险台账） | 10-01 | 4 |
| `plan-pr55-disposition-2026-10-04.md` | 已全部执行完毕（甲档 S1-S8） | 10-05 | 5 |

### 3.2 V3 执行平台与交付路线

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-v3-execution-platform-final-architecture-2026-09-22.md` | 规划文档（架构总纲，不实现代码） | 09-23 | 12 |
| `plan-enterprise-platform-skeleton-2026-09-23.md` | **已被取代** — 见 `docs/architecture/agent-execution-platform.md`；2026-10-15 补「依据/去处」行（两份评审为判定原件），并标出 `AGENTS.md` 第 5 行仍列本件为真相源的冲突（待订正） | 09-23 | 4 |
| `v3-roadmap-breakdown.md` | 规划文档（v3 评审稿），不实现代码 | 08-22 | 9 |
| `plan-v3-phase-2-4-integration-2026-09-23.md` | 方案文档 v2，待确认后施工 | 09-23 | 0 |
| `plan-v3-phase-3.4-awaitable-integration-2026-09-23.md` | 设计文档 + 实现中 | 09-23 | 0 |
| `plan-v3-identity-merge-2026-10-01.md` | 已拍板并在执行中 | 10-01 | 2 |
| `plan-production-delivery-roadmap-2026-10-09.md` | 未标（一期阶段 0–3；正文本轮有 2026-10-14 订正） | 10-09 | 4 |
| `plan-v3-unwired-landing-2026-10-15.md` | **原批 5/5 + 续批 §6/§7 均已落地**（未部署；真 PG 并发双写与双实例故障转移判据仍「待环境」） | 10-15 | 12 |
| `plan-unfinished-completion-schedule-2026-10-16.md` | **现行执行排期**（§0 截止日 / §2 排期 / §3 = 真待拍板 20 项 / §16 七条标准复取 / §25–§26 本批复跑留档） | 10-16 | 22 ★ |

### 3.3 P0 / P1 / P2 缺陷与门禁整改

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-p0-1-scheduler-gating-option-b-2026-09-24.md` | 未标 | 09-24 | 2 |
| `plan-p0-4-blind-except-ratchet-2026-09-24.md` | M1 棘轮已落地 + **M2 策略修订**（2026-10-15 补现值复测段，本件角色=过程记录） | 09-24 | 12 |
| `plan-p0-4-blind-except-real-reduction-2026-09-24.md` | ✅ 已批准（2026-09-24 逐站实地核查后修订）；2026-10-15 补「现行执行方案」状态行 | 09-24 | 7 |
| `plan-p0-ha-tenant-fixes-2026-09-25.md` | 未标 | 09-25 | 2 |
| `plan-p1-4-lightweight-schema-migrations-2026-09-24.md` | **已落地**（`753e5625`，25 个迁移文件 + `schema_migrations` 元表；CRLF 假阳性坑已记在文内） | 09-24 | 0 |
| `plan-p1-6-dual-vector-store-2026-09-24.md` | **短期 C 已落地 / 长期 A 未评估**（验收 3 条：1 成、2 未做、3 存疑不翻勾） | 09-24 | 0 |
| `plan-p2-unified-exception-handlers-2026-09-24.md` | 未标（AGENTS.md 以「P2 范例」引用其结论） | 09-24 | 4 ★ |
| `p0-execution-retrospective-2026-09-24.md` | 未标（复盘件） | 09-24 | 3 |
| `p2-bucket-b-reduction-findings-2026-09-24.md` | **已定案：桶 B 不做**（2026-10-15 补状态行，判据留档件，非待执行项） | 09-24 | 0 |

> **2026-10-15 合并评估（B）——这组决定不合并**：blind-except 四件（`ratchet` / `real-reduction` / `p2-bucket-b-reduction-findings` + 数据件 `p0-4-blind-except-inventory.txt`）逐篇读过之后确认：它们是**有互指的三段链条**（M1 棘轮落地 → M2 放弃逐点 noqa → 第三条路三桶规则 → 桶 B 定案不做），`ratchet` 内部已自标"取代下方原方案"，`real-reduction` 前置行又指回它。合成一篇会把已经成立的指认关系拆成断链。
> 改做的动作：四件各落「状态 / 去处」行，并补一次复测现值 —— `uv run --with ruff ruff check --isolated --select BLE001,S110 --statistics .` = **263 处（BLE001 234 + S110 29）/ 100 文件**，较 M1 基线 262 处 / 103 文件**净量未降（构成变了）**；同时标出 `docs/TODO.md` D7 里"M2 之前的逐文件烧除"这句过期措辞（D7 保持未核销）。
> `p0-4-blind-except-inventory.txt` 是脚本可解析的数据件（每行 `file:line:col CODE msg`），**故意不加注释、不改写**，过期只在本索引声明。

### 3.4 观测 / 追踪 / Langfuse

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-observability-global-remediation-2026-09-29.md` | 已闭环（代码面全收口 + 真集群端到端复验 2026-09-30） | 09-30 | 8 ★ |
| `plan-langfuse-wiring-2026-10-13.md` | 未标（正文含"已完成"字样，未构成状态行） | 10-13 | 9 |
| `plan-observability-target-model-2026-10-14.md` | 未标 | 10-14 | 3 |
| `plan-tracing-shutdown-flush-timeout-2026-10-10.md` | 未标 | 10-10 | 4 |
| `plan-tool-instrumentation-choke-point-2026-09-25.md` | ✅ 已落地（v3.1 定板 + 批 0/1…） | 09-25 | 3 |
| `plan-forensic-provenance-wiring-2026-10-16.md` | **Proposed（待拍板，不授权编码）**：roadmap §四 第 6 条缺口的方案，含 Q1–Q5 五问；§1.1 记有一条实测——记录级取证在 PG 侧不落库 ⇒ 缺口是两层（字段填充 + 持久化读回） | 10-16 | 5 |

### 3.5 记忆 / 身份 / 隔离 / 租户

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-memory-hardening-2026-09-27.md` | 未标（正文含"已落地"字样，T2–T8 需逐条对） | 10-02 | 9 ★ |
| `plan-memory-identity-workspace-2026-10-14.md` | 未标（现状事实卡 + 五阶段方案，不动代码） | 10-14 | 3 ★ |
| `plan-identity-gate-6of6-2026-10-16.md` | **实施方案（只覆盖可独立执行的一半）**：6/6 装配点 + P13 归属门禁已落地；fork 收敛与 enforce 现网取证显式转待拍板/待环境 | 10-16 | 6 |
| `plan-memory-backend-stale-embed-signature-2026-10-10.md` | 未标 | 10-10 | 1 |
| `plan-tenant-identity-2026-09-27.md` | 未标（正文含"待执行"字样） | 09-27 | 3 |
| `plan-isolation-hardening-2026-09-27.md` | 未标 | 09-27 | 8 ★ |
| `plan-query-tenant-from-client-not-server-asserted-2026-10-10.md` | 未标（缺陷件，结论已落 ADR-0007） | 10-13 | 6 |
| `plan-audit-operator-principal-2026-10-03.md` | **待拍板**（未动一行业务代码） | 10-03 | 7 ★ |
| `m5-semantic-cache-plan.md` | 未标（TB-4 记其为「纯草案，未实施」） | 08-22 | 1 |

### 3.6 文档防漂移 / 取证脚本 / 评审裁定

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-doc-sync-file-ref-gate-2026-10-01.md` | 未标 | 10-01 | 5 |
| `plan-doc-sync-tracked-scope-2026-10-04.md` | 未标（结论已入 AGENTS.md 防漂移段） | 10-04 | 9 ★ |
| `plan-evidence-scripts-intake-2026-10-04.md` | 已拍板候选 ①（本文件即方案本体） | 10-04 | 7 ★ |
| `plan-review-findings-closeout-2026-10-04.md` | 未标 | 10-04 | 2 |
| `plan-multi-expert-adjudication-2026-09-30.md` | 未标 | 10-02 | 4 |
| `plan-branch-disposition-2026-10-01.md` | 未标（正文含"已被"处置表述） | 10-02 | 4 |
| `arch-audit-2026-09-24.md` | 未标 | 09-24 | 12 |

### 3.7 技术债与结构收敛

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-tech-debt-cleanup-2026-09-22.md` | P0+P1+P2(T2.1/T2.3) 已完成，T2.2/T2.4 续办；块内复选框口径见 §5 | 09-22 | 8 |
| `plan-tech-debt-followup-2026-09-22.md` | 未标（AGENTS.md 点名 D1-D10 追踪面） | 09-24 | 10 ★ |
| `plan-tech-debt-env-var-rename.md` | 仓库内已完成（2026-09-22）；126 部署脚本待同步 | 09-23 | 1 |
| `plan-structural-debt-cleanup.md` | 2026-09-22 制定并实施 | 09-23 | 1 |
| `plan-duplicate-logic-inventory-2026-10-01.md` | 未标 | 10-01 | 1 |
| `plan-e-dual-track-convergence.md` | P4.1~P4.3 全部实施完成 | 08-22 | 12 |
| `plan-agentic-skill-convergence.md` | **已落地（契约层 3/3）**，但默认部署下该注册走 except 跳过——不得说成"agentic 现网可用" | 09-22 | 0 |
| `skill-consolidation-inventory.md` | 未标（AGENTS.md 点名其为 Skill 收敛盘点） | 09-23 | 3 ★ |
| `tool-mount-matrix-2026-09-25.md` | 未标 | 09-25 | 3 |

### 3.8 早期（08 月）与零散件：多数无状态行、且零提及

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-m3-m5-logging-pool.md` | Approved with changes（M5）/ M3 已修订 | 08-22 | 2 |
| `plan-m11-exception-classification.md` | Proposed | 08-22 | 1 |
| `plan-tests-reorg.md` | **已落地**（根 `tests/` 扁平文件实测 0、§二 十个子目录全在；`dialogue_framework/`+`wenda_data_agent/` 已不在 tests/ 下，去向未查） | 08-22 | 0 |
| `plan-fix-validate-config.md` | **已落地**（`4b7bbb34`）；⚠️ **成因订正：是回归不是遗漏**——`c45e1354` 重构时删掉了定义与 `__all__` 导出 | 08-22 | 0 |
| `plan-c2-audit-atomic-write-2026-09-23.md` | **已落地 5/5**（收敛到 `foundation/_audit_writer.py`，tmp+`os.replace`）；残差＝无 lint 防回潮 | 09-23 | 0 |
| `plan-c2-cross-agreement-pivot-2026-09-29.md` | 未标 | 09-30 | 3 |
| `plan-fix-f-s0-08-zhanggui-rename.md` | 已实施（2026-09-21） | 09-21 | 1 |
| `plan-fix-f-s1-01-test-reverse-import.md` | 已实施（2026-09-21，方向 B 迁测试） | 09-21 | 1 |
| `plan-fix-f-s1-05-contract-revise-to-rest.md` | 未标 | 09-21 | 7 |
| `plan-exhibition-p0-p1-landing.md` | 未标 | 09-22 | 3 |
| `plan-intent-embedder-bypasses-provider-2026-10-10.md` | **只出方案，未动代码** | 10-12 | 4 |
| `plan-router-keyword-gate-hides-corpus-2026-10-12.md` | **待拍板，未改代码** | 10-13 | 11 |
| `plan-schema-drift-existing-db-gap-2026-10-10.md` | 未标 | 10-10 | 2 |
| `plan-history-read-uses-nonexistent-checkpointer-api-2026-10-10.md` | 已随本方案落地修复 | 10-10 | 2 |
| `plan-rag-sparse-encoding-consistency-2026-09-29.md` | 已确认并在 126 容器实跑完成 | 09-29 | 4 |
| `plan-workspace-toplevel-eval-disambiguation-2026-09-25.md` | 已确认执行 | 09-25 | 3 |

## 4. 证据与历史层（留档，不外引、不改写）

- `docs/operations/evidence/` — 6 个日期目录、每份一个 `readings.md`。**每份的读数只绑定当时的 Pod `GIT_REV`**，换 rev 后须复跑，不得当现值引用。留档件是否入库由每次处置单独定：`2026-10-14-3node-deployment` 的原始 stdout（`raw.txt`）已于 2026-10-15 按需清除，回看用 `git show da96d870:docs/operations/evidence/2026-10-14-3node-deployment/raw.txt`，机侧另有一份在 `126:/tmp/inv-out.txt`（**清掉它就两处皆无**）。
- `docs/architecture/overview.html`（11 KB，09-23）— `docs/` 里唯一非 md 的架构产物，无入站引用；它不会被 `check_doc_sync.py` 覆盖，改动架构文档时不会有人提醒你同步它。
- `docs/analysis/2026-09-21/` — 9 份（`INDEX.md` / `PRIORS.md` / `PROMPT.md` / `00`~`05`）。该目录自带 `INDEX.md`，本索引不重复其内容；`02-debt-diagnosis.md` 提及 17 次，是这批里唯一仍被大量引用的。
- `docs/reviews/` — 2 份评审件（09-23，均已在 2026-10-15 补「后续处置」行）：对骨架方案的否定**已被采纳**；`review-v3-vs-skeleton-comparison` 给 V3 的第一条待补强**已按原文落实**（`agent-execution-platform.md` 第 35 行「与 8 层总纲的映射」），第二条（§27 目录逐行核对）**未核**，不得当已闭环。`docs/research/` — 4 份调研（08-22 ~ 09-25，其中 `deepseek-harness-discussions-analysis.md`、`code-agent-borrowable-features.md` 零提及）。
- `docs/tech-debt/` — 2 份：`tech-debt-audit-2026-09-22.md`（管「识别」）与 `tech-debt-hardcoded-logic.md`。与 `agent-harness-capability-map.md`（管现状）、`docs/TODO.md`（管排期）三套台账互不联动，判「会不会修」必须 grep TODO。
- `docs/handoff-2026-08-21.md`、`docs/fix-exhibition-agent-review-issues.md` — 交接与专项修复件，日期即封存。
- `docs/adr/0003`、`docs/ha/ha-durable-execution.md`、`docs/operations/deployment.md` 等 08-22 旧件：仍可能被现网事实推翻，引用前先在 §3 找有没有更晚的同主题 plan。

## 5. 新文档必须带的状态行（这次问题的根因）

71 篇 plan 正文里只有 29 篇开头有可辨状态行 ⇒ 没人能判断哪篇作数。今后 `docs/plans/` 新增一律在标题下第二行写：

```markdown
> 状态：<未拍板 | 已拍板待施工 | 施工中 | 已落地(<commit 或 PR>) | 已被 <文件路径> 取代 | 仅存档（结论已回写至 <文件>）> ｜ 依据：<代码/测试/命令实测的一条可复跑证据> ｜ 回写：落地后必须回来改本行
```

三条配套规则：① 结论落到活文档后就地改状态行为「仅存档 + 回写去处」，不要留一篇"看起来还待办"的旧稿；② 同一缺陷只留一篇主文，其余在状态行写「已被 X 取代」；③ 复选框只在**该文件既有范式是翻勾**时翻，且翻勾必须在行内写依据 + 声明块内计数口径（例：`plan-tech-debt-cleanup-2026-09-22.md` T0.2 块标题写「6 项」而实列 12 个复选框）。

## 6. 本轮没做的事

- **未移动、未删除任何文件**。2026-10-15 做过一次**内容合并**（合并 A：`runtime-analysis-overview.md` 的六块内容并入 `runtime-self-build-analysis.md`，源文件保留降级为寻址页）；`docs/plans/` 零提及的 9 篇一律保留。移动会改引用路径，`check_doc_sync.py` 只校验 AGENTS.md / ARCHITECTURE.md / README.md 三篇，它绿不代表其余 docs 的引用没断。
- **「未标」不等于「已了结」**：判"有没有状态行"的口径 = `head -25 <文件> | grep -qE "状态[^。；]{0,14}[:：]"`，实测 **42 命中 / 29 未命中**（71 篇 md 中）。**2026-10-16 重测 = 82 篇 / 52 命中 / 30 未命中**（分母随新 plan 入库增长；§7 那份清单**依然成立**——原 29 篇仍全部缺状态行，新增的 1 篇是 `docs/plans/README.md`，属目录索引不是 plan，不计入待补工作面）。⚠️ 这个口径会漏掉「状态订正（2026-10-15 补）：」这类冒号前超过 14 字的写法，今天有两篇被它漏计（含 `p2-bucket-b-reduction-findings`），所以 **29 是上界不是精确值**；名单见 §7。
- 本索引自身的状态列是**摘录**，不是我对每篇结论的重新核实。任何一篇的数字要拿去对外用，仍按原文件的取证口径复核。

## 7. 待补状态行清单（②的剩余工作面，29 篇待补 ｜ 2026-10-16 复核：以下每一篇仍缺状态行）

按 §6 命令实测 29 篇未命中，其中 `p2-bucket-b-reduction-findings-2026-09-24.md` 是口径漏计（它写的是「状态订正（2026-10-15 补）：」，冒号前 18 字超出 14 字窗口，实际**已补**）⇒ 真待补 28 篇。

- `arch-audit-2026-09-24.md`
- `dep-security-accepted-risks-2026-09-25.md`
- `m5-semantic-cache-plan.md`
- `p0-execution-retrospective-2026-09-24.md`
- `plan-branch-disposition-2026-10-01.md`
- `plan-codeql-codescanning-remediation-2026-10-01.md`
- `plan-dependabot-21-alerts-closure-2026-09-30.md`
- `plan-doc-sync-tracked-scope-2026-10-04.md`
- `plan-duplicate-logic-inventory-2026-10-01.md`
- `plan-isolation-hardening-2026-09-27.md`
- `plan-langfuse-wiring-2026-10-13.md`
- `plan-memory-backend-stale-embed-signature-2026-10-10.md`
- `plan-memory-identity-workspace-2026-10-14.md`
- `plan-observability-target-model-2026-10-14.md`
- `plan-p0-1-scheduler-gating-option-b-2026-09-24.md`
- `plan-p0-ha-tenant-fixes-2026-09-25.md`
- `plan-p2-unified-exception-handlers-2026-09-24.md`
- `plan-production-delivery-roadmap-2026-10-09.md`
- `plan-query-tenant-from-client-not-server-asserted-2026-10-10.md`
- `plan-review-findings-closeout-2026-10-04.md`
- `plan-schema-drift-existing-db-gap-2026-10-10.md`
- `plan-tech-debt-followup-2026-09-22.md`
- `plan-tenant-identity-2026-09-27.md`
- `plan-tracing-shutdown-flush-timeout-2026-10-10.md`
- `production-delivery-anchor-map-2026-10-09.md`
- `skill-consolidation-inventory.md`
- `tech-debt-multi-agent-2026-09-23.md`
- `tool-mount-matrix-2026-09-25.md`

补法固定三步：读正文定它自述要干什么 → 对代码 / 对 `docs/TODO.md` 判做没做 → 只写一行「状态｜依据｜回写」，**不改原结论、不翻别人的复选框**。批 1（10-15 已提交）的收获可作参照：6 篇里 **5 篇其实早已落地**、1 篇短期方案落地长期未评估，另有 1 篇的**成因定性被证伪**（`plan-fix-validate-config.md`：不是"从未实现"，是重构静默摘除后次日以"缺失"名义补回）。
