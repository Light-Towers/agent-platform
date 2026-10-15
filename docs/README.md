# docs 索引 · 哪篇作数、哪篇只是历史

> 本文件由 2026-10-15 的文档治理生成：**未删除、未移动任何文档**，只做分层与状态登记。
> 现状：`docs/` 141 个文件 / 约 2.6 MB；其中 `docs/plans/` 72 个文件 = 71 篇 md + 1 份配套盘点件 `p0-4-blind-except-inventory.txt`。71 篇 md 里 **29 篇文内有可辨状态行、42 篇没有**。

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
| `plan-enterprise-platform-skeleton-2026-09-23.md` | **已被取代** — 见 `docs/architecture/agent-execution-platform.md` | 09-23 | 4 |
| `v3-roadmap-breakdown.md` | 规划文档（v3 评审稿），不实现代码 | 08-22 | 9 |
| `plan-v3-phase-2-4-integration-2026-09-23.md` | 方案文档 v2，待确认后施工 | 09-23 | 0 |
| `plan-v3-phase-3.4-awaitable-integration-2026-09-23.md` | 设计文档 + 实现中 | 09-23 | 0 |
| `plan-v3-identity-merge-2026-10-01.md` | 已拍板并在执行中 | 10-01 | 2 |
| `plan-production-delivery-roadmap-2026-10-09.md` | 未标（一期阶段 0–3；正文本轮有 2026-10-14 订正） | 10-09 | 4 |

### 3.3 P0 / P1 / P2 缺陷与门禁整改

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-p0-1-scheduler-gating-option-b-2026-09-24.md` | 未标 | 09-24 | 2 |
| `plan-p0-4-blind-except-ratchet-2026-09-24.md` | 未标（与下行同题，见 real-reduction 行） | 09-24 | 12 |
| `plan-p0-4-blind-except-real-reduction-2026-09-24.md` | ✅ 已批准（2026-09-24 逐站实地核查后修订） | 09-24 | 7 |
| `plan-p0-ha-tenant-fixes-2026-09-25.md` | 未标 | 09-25 | 2 |
| `plan-p1-4-lightweight-schema-migrations-2026-09-24.md` | 未标 | 09-24 | 0 |
| `plan-p1-6-dual-vector-store-2026-09-24.md` | 未标 | 09-24 | 0 |
| `plan-p2-unified-exception-handlers-2026-09-24.md` | 未标（AGENTS.md 以「P2 范例」引用其结论） | 09-24 | 4 ★ |
| `p0-execution-retrospective-2026-09-24.md` | 未标（复盘件） | 09-24 | 3 |
| `p2-bucket-b-reduction-findings-2026-09-24.md` | 未标（findings 件） | 09-24 | 0 |

### 3.4 观测 / 追踪 / Langfuse

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-observability-global-remediation-2026-09-29.md` | 已闭环（代码面全收口 + 真集群端到端复验 2026-09-30） | 09-30 | 8 ★ |
| `plan-langfuse-wiring-2026-10-13.md` | 未标（正文含"已完成"字样，未构成状态行） | 10-13 | 9 |
| `plan-observability-target-model-2026-10-14.md` | 未标 | 10-14 | 3 |
| `plan-tracing-shutdown-flush-timeout-2026-10-10.md` | 未标 | 10-10 | 4 |
| `plan-tool-instrumentation-choke-point-2026-09-25.md` | ✅ 已落地（v3.1 定板 + 批 0/1…） | 09-25 | 3 |

### 3.5 记忆 / 身份 / 隔离 / 租户

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-memory-hardening-2026-09-27.md` | 未标（正文含"已落地"字样，T2–T8 需逐条对） | 10-02 | 9 ★ |
| `plan-memory-identity-workspace-2026-10-14.md` | 未标（现状事实卡 + 五阶段方案，不动代码） | 10-14 | 3 ★ |
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
| `plan-agentic-skill-convergence.md` | 未标 | 09-22 | 0 |
| `skill-consolidation-inventory.md` | 未标（AGENTS.md 点名其为 Skill 收敛盘点） | 09-23 | 3 ★ |
| `tool-mount-matrix-2026-09-25.md` | 未标 | 09-25 | 3 |

### 3.8 早期（08 月）与零散件：多数无状态行、且零提及

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-m3-m5-logging-pool.md` | Approved with changes（M5）/ M3 已修订 | 08-22 | 2 |
| `plan-m11-exception-classification.md` | Proposed | 08-22 | 1 |
| `plan-tests-reorg.md` | Proposed | 08-22 | 0 |
| `plan-fix-validate-config.md` | 未标 | 08-22 | 0 |
| `plan-c2-audit-atomic-write-2026-09-23.md` | 未标 | 09-23 | 0 |
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
- `docs/reviews/` — 2 份评审件（09-23）。`docs/research/` — 4 份调研（08-22 ~ 09-25，其中 `deepseek-harness-discussions-analysis.md`、`code-agent-borrowable-features.md` 零提及）。
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

- **未删除、未移动、未合并**任何文件（含 `docs/plans/` 零提及的 9 篇）。移动会改引用路径，`check_doc_sync.py` 只校验 AGENTS.md / ARCHITECTURE.md / README.md 三篇，它绿不代表其余 docs 的引用没断。
- **「未标」不等于「已了结」**：上表 42 篇文内没有状态行，要补就得逐篇读正文并附依据，本轮未做。
- 本索引自身的状态列是**摘录**，不是我对每篇结论的重新核实。任何一篇的数字要拿去对外用，仍按原文件的取证口径复核。
