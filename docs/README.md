# docs 索引 · 哪篇作数、哪篇只是历史

> 本文件由 2026-10-15 的文档治理生成：**未删除、未移动任何文档**，只做分层与状态登记。
> 现状（**2026-10-30 重取，以下每个数都带口径与复现命令**；2026-10-27 那组「173 / 173 / 3.8 MB / 103 入库 / 94 篇 / 51 命中」只在同口径下可比，现值见下）：`docs/` **196 个入库文件 / 196 个工作区文件**（已一致；`git ls-files docs | wc -l` 对 `find docs -type f | wc -l`）；体积 **3.9 MB**（`du -sh docs`）。其中 `docs/plans/` **108 个入库文件**，顶层 md **99 篇**（入库数与工作区数已一致，复现 `git ls-files docs/plans | grep -cE '^docs/plans/[^/]+\.md$'`）。99 篇按 §6 口径重跑 `uv run python -B scripts/evidence/recount_plan_status_lines.py`：**56 篇有可辨状态行 / 43 篇未命中**，其中 1 篇是该口径的已知漏计（`p2-bucket-b-reduction-findings-2026-09-24.md` 实已有状态行）⇒ **真待补 42 篇**。两条值得单独看一眼的读数：未命中数与 2026-10-27 那次**相同**（都是 43），涨的 5 篇全落在命中侧 ⇒ 近三周新写的 plan 一条没漏状态行，这是 §5 那条纪律的现场效果，不是巧合。**本机是 Windows**：上面 `wc -l` / `find` / `du` / `grep -c` 四条本机无对应，实跑用等价 PowerShell 式 `(git ls-files docs).Count`、`(Get-ChildItem -Recurse -File docs).Count`、`(Get-ChildItem -Recurse -File docs | Measure-Object -Sum Length).Sum`、`(git ls-files docs/plans | Where-Object { $_ -match '^docs/plans/[^/]+\.md$' }).Count`，两套命令给出同一组数。（旧数「141 个文件 / 约 2.6 MB / 72 个文件 = 71 篇 md / 42 有状态行 · 29 未命中」是 2026-10-15 的快照，保留在此只为让后来人看得见它涨了多少，**不得当现值引**。）

## 1. 三条判据（先读这个，别先翻目录）

1. **文件名带日期 ⇒ 它是当日快照，不是活文档**。仓库既有纪律：dated 证据文件留档、不外引。要改结论请改不带日期的那篇，然后让快照保持原样。
2. **一篇 plan 是否还活着，只看三件事**：① 被 AGENTS.md / ARCHITECTURE.md / README.md 点名（下表标 ★）；② 文内状态行写着「待拍板 / Proposed / 实现中」；③ `docs/TODO.md` 里有对应条目。三者皆无 ⇒ 视为已了结，不必读正文。
3. **状态只有两种可信来源**：文内自述（下表「自述状态」列即原文摘录），或本轮补写且附依据。标「未标」的篇目**含义是我还没读过正文**，不许从文件名推断它做了什么。

## 2. 活文档层（无日期后缀，可当现值引用）

| 文件 | 作用 | 提及 |
|---|---|---|
| `docs/TODO.md` | 排期台账（判「会不会修」的唯一面） | 98 |
| `docs/architecture/agent-harness-capability-map.md` | 能力现状地图（管「现在有没有」） | 4 ★ |
| `docs/architecture/architecture-improvement-plan.md` | 优化项 A~I（原文含独立的优化 I，原记 A~H 漏计） + 技术债登记 TB-1~TB-14 + §0.1 内核契约 | 20 ★ |
| `docs/architecture/architecture-boundary-app-vs-agent-federation.md` | 双轨职责边界 | 12 ★ |
| `docs/adr/0005-execution-memory-kernel-contract.md` | 执行/记忆内核契约 | 5 ★ |
| `docs/adr/0006-isolation-dimension-contract.md` | 隔离维度契约 | 5 ★ |
| `docs/adr/0007-server-asserted-tenant-identity.md` | 服务端断言租户 | 7 ★ |
| `docs/adr/0008-auth-mode-selection.md`、`docs/adr/0009-vector-store-selection.md`、`docs/adr/0010-ui-stack-selection.md` | **roadmap #24 三项悬置选型的决策记录**（认证方式 / 两套向量存储 / 界面）。三篇状态并不相同：`0009` / `0010` **未决**，`0008` 为 **部分已决 + 三项未决**（内部租户身份=RS256 JWT + 内部 HMAC 头已实施，对外入口凭据等三项待拍板）；三篇均内含已决边界、选项代价、否决理由、重启条件，以及各一行「待用户回答」⇒ 引用时不得当作已定选型 | 0（2026-10-16 新建；由 `docs/plans/plan-production-delivery-roadmap-2026-10-09.md` #24 与 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §13 指向） |
| `docs/operations/testing-playbook.md` | 分层验证与实跑配方 | 29 ★ |
| `docs/operations/env-126-inventory.md` | 内网三机部署态基线（读数绑 rev） | 14 ★ |
| `docs/operations/minimal-release-runbook.md` | 上台手册（含「这是多 agent 吗」标准答法 §11）。⚠️ 本文里的 `SQL_DSN` / `sql_backend` 描述是 2026-10-28 前的史实，头注已标 | 11 ★ |
| `docs/operations/nl2sql-release-checklist.md` | **问数上线（批次 6）的现网落差清单 + 逐条判据**：6 项“清单声明 vs 集群实况”落差（带只读取数命令）+ 10 步上线序列（每步写清期望读到什么、读不到说明什么）+ 取证/回滚/卡住的两个 D2 输入。落档那一轮集群零写操作，**落差读数必须复跑 §2 再引** | 4（2026-10-28 新建；由 `AGENTS.md` 内网环境段、`minimal-release-runbook.md` 头注与 `CHANGELOG.md` 批次 5 节两处指向，不含本行） |
| `docs/operations/observability-pitfalls.md` | 观测面坑档 | 5 ★ |
| `docs/operations/unconfirmed-items.md` | **无法确认清单**（活文档）：本窗口所有"我试了但证不了"的事按 待环境 / 待放行 / 待拍板 / 口径未定 / 他人负责 / 已撤回断言 六类集中，每条自带**解锁动作**与"证不了的原因"。规则：任何一条都不许被引成"已验证"；确认后改状态不删行 | 2（2026-10-16 新建；由台账 §30 与 CHANGELOG 未发布窗口节指向） |
| `docs/operations/demo-questions.md` | 演示问答口径 | 5 |
| `docs/plans/plan-f-single-runtime-multi-planner.md` | Plan-F 演进总纲（AGENTS.md 顶部指向） | 13 ★ |
| `docs/plans/production-delivery-anchor-map-2026-10-09.md` | 交付锚点取证（带日期但被活文档点名，见 §4 注） | 7 ★ |
| `docs/plans/skill-consolidation-inventory.md` | Skill 收敛盘点 | 3 ★ |
| `docs/plans/tech-debt-multi-agent-2026-09-23.md` | 多 Agent 技术债 | 3 ★ |
| `docs/project-introduction-2026-10-12.md` | **对外唯一交付稿**（讲解用，禁词见文内纪律） | 1 |
| `docs/runtime-self-build-analysis.md` + `docs/opensource-runtime-counterparts.md` | 业界对照族（框架层 / 内核原语层） | 4 / 0 |
| `docs/runtime-analysis-overview.md` | **已并入** `runtime-self-build-analysis.md`（2026-10-15 合并 A），本页仅作旧链接寻址 | 0 |
| `docs/adr/0003-dual-db-driver.md` ~ `docs/adr/0004-typed-memory-kernel.md` | 早期 ADR，`0004` 状态仍为「修订中」 | 0 / 3 |
| `docs/adr/0011-two-text2sql-paths-convergence.md` | **两条 Text2SQL 路收敛**（2026-10-18 拍板选项 A：`agent_server/sql` 退役、统一到 nl2sql-service）；§1–§6 是拍板前分析，§7 起是执行记录（§7.3 = 2026-10-28 批次 5 拆 `/health` 的 `sql_backend` 假灯并推翻 §7.2 第 3 行） | 2（2026-10-28 取，不含本行；2026-10-27 那次为 0 ⇒ 本轮新增两处指向：runbook 头注与上线清单） |

未入库、只在本机存在的一篇：docs/agno-agentos-comparison.md（平台层竞品对比，未提交，clone 后不存在，故按 AGENTS.md 防漂移规矩不以反引号路径书写）。

**2026-10-26 追记 · 本表此前漏点两篇 ADR**（改前本索引正文里 docs/adr/0012、docs/adr/0013 命中数为 0；⚠ 这两个短名自刀㉗ 起不带反引号 —— 本句说的就是「当时正文里没出现过这两个字面串」，反引号会把它读成真实路径）：
- `docs/adr/0012-nl2sql-branch-consolidation.md` —— 分支收敛与删除死枝的依据登记（AGENTS.md《分支卫生》第 4 条指向它）。
- `docs/adr/0013-semantic-cache-single-track.md` —— 语义缓存单轨拍板（Accepted C：Valkey 唯一实现，生产与开发测试都用它；PG 缓存退役、无自动回退）。**2026-10-27 补记：该件已入库**（`git ls-files` 命中），按纪律补回反引号并已复跑 `scripts/check_doc_sync.py`；§9 是变异战役读数、§11 是逐条变更台账（本行追加后至第 58 行）。
- `docs/adr/0014-web-poc-integration-branch-exception.md`（2026-11-02 新增）—— **`feat/web-visual-poc` 转正为唯一集成分支**，并把 `company` 远端 heads 按 3 条登记为知情例外（计数口径改为「不含历史锚 ref 与公开镜像侧载体」）；§5 是五条复审触发条件。`AGENTS.md`《分支卫生》那句「远端恒 2 分支」在本仓的读法以该件为准，`docs/operations/branch-hygiene-monthly-checks.md` 的 2026-11-02 节指向它。

## 3. `docs/plans/` 71 篇 md 分层（按主题簇）

「自述状态」= 文内状态行摘录；「未标」= 文内没有可辨状态行，**需读正文才能定**。提及数为全仓入库文件中该文件名的出现次数（含 CHANGELOG 历史条目与自身提及），只作相对热度，不作"仍在用"的证据。

> **2026-10-16 追记（本层新增 4 行，其余行未动）**：本节写就时是 71 篇，现值为**顶层 `docs/plans/*.md` 入库 75 篇 / 文件系统 76 篇**（差的 1 篇是并行会话新建、此刻尚未入库的 plan-deep-research-app-2026-10-16.md——**按 AGENTS.md「不入库路径不用反引号」的纪律这里写成普通文本**，且**本索引不代登**，由它自己的会话登记）。复取命令：`git ls-files docs/plans | grep -cE '^docs/plans/[^/]+\.md$'`。新登记的四篇：`plan-v3-unwired-landing-2026-10-15`、`plan-unfinished-completion-schedule-2026-10-16`、`plan-identity-gate-6of6-2026-10-16`、`plan-forensic-provenance-wiring-2026-10-16`。
> **两条没有重取、不得当现值引**：① 顶部第 4 行的「42 篇有状态行 / 29 篇未命中」与 §7 名单仍是 2026-10-15 快照（上面四篇都**有**可辨状态行，但按 §6 口径命令未重跑）；② 四行的「提及」数在本批合入后会各自 +1 以上（新行本身就是新增引用），复现请用 `git grep -c -o -- "<文件名>" | awk -F: '{s+=$NF} END{print s}'` 现取。
> **2026-10-27 复核**：上上行的「75 / 76」是 2026-10-16 时点值，**不得当现值引**；顶层 `docs/plans/*.md` 入库现为 **94 篇**（与顶部现状行同源，复现 `git ls-files docs/plans | grep -cE '^docs/plans/[^/]+\.md$'`；若写成 `git ls-files 'docs/plans/*.md'` 会因 git pathspec 的 `*` 跨目录而多算 8 个 `docs/plans/archive/` 文件、得 102，两个数都成立但口径不同）。本节标题的「71 篇」同样是写就时的快照，未改。**2026-10-30 再取 = 99 篇**（以顶部现状行为准）；本轮重取时发现四个已入库的活件一直未登记（前端三件 + 脱敏门禁自披露一件），已在 §3.6 / 新增 §3.9 补齐——它们被 AGENTS.md 不点名、只在彼此文内互引，按 §1 判据 ② 它们活着，但按本索引的可发现性它们等于隐形的。

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
| `plan-unfinished-completion-schedule-2026-10-16.md` | **现行执行排期**（§0 截止日 / §2 排期 / §3 = 真待拍板 21 项 / §16 七条标准复取 / §25–§28 本批留档） | 10-16 | 22 ★ |

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
| `plan-ci-execution-plane-2026-11-02.md` | **Proposed（D2 待拍板）**，刀㉕ 新增。它回答的不是「代码质量」而是「**门禁到底在哪执行**」：三种绿（本地 / 容器 / 服务端）对照 + 四条路径（A 借公开镜像、拒；B 内网 GitLab CI、唯一真解但需 D2；C 容器绿常态化；D 维持现状＝登债）+ 三步可逆迁移 + 五格非空转反证表。**本刀零代码**（未新建 .gitlab-ci.yml、未改 workflow、未动 `Makefile`）。⚠ **与本簇其余行的不同**：它是**执行面**这一独立轴，不属 PR-0 开工前置，也不在 §3.9 那三件互指关系里；它的现状表全部绑取数时刻（公开宗随时可能新增 run），**引用前按该文 §9 复跑** | 11-02 | —（本行不抄数：计数会被登记它自己的文字推动，口径见 §3.9 末那段） |

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
| `plan-public-mirror-gate-selfdisclosure-2026-10-29.md` | 原文自述 **Proposal（待拍板，未动代码）**；读数绑定 rev `896f966e` ⇒ 换 rev 须复跑。同族的 D26（scratch 脚本引用不入库声明）已于 2026-10-30 处置并回写 evidence-format，**本件的待拍板项不因此自动解除** | 10-29 | 7 |
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
| `plan-mongo-probe-timeout-single-impl-2026-10-30.md` | **已拍板方向（D27=b），待施工**：只出方案，未动一行产品代码。**2026-10-30 答复批**：两个待答已答完（默认值 `2000` 已确认 / 排期 = **前端之后**）⇒ 文中无欠答项，但 S1 **未获开工授权**（排期在后 ≠ 已批动工）；它带来的 `/health` 可见性排除项已按用户意见登进 `docs/TODO.md` §6（不入本台账 §3） | 10-30 | 5 |
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

### 3.9 前端与界面（ADR-0010 由「未决」落为已决 C 之后新长出来的一簇）

> 三件彼此互指：选型件定栈、工程件定怎么做（§7 工单表 + §9 文件清单是 PR-0 的唯一入口）、完整性件只阻塞 PR-3。**拿 PR-0 开工时不得只读其中一件**：只读选型件会重评一轮栈（§11.2 那个同名异义坑就是这么来的），只读工程件会拿 PR-3 的未定形状当已定做。
>
> **（2026-10-30 同日第二批）下面多出来的一对**：视觉件（§13.1 六格的答卷：tokens 层、色值、图例、断点、三态、V1–V7）+ 它的取证件。两个状态都是**待用户点头**，开工授权仍未给。它们让上面那句「唯一入口」多一个限定：**PR-0 的样式层取值在视觉件里，不在工程件里**（工程件 §7/§9.3 只登记了落点与文件清单，色值一个都没抄——抄就会两处漂）。

| 文件 | 自述状态 | 末次 | 提及 |
|---|---|---|---|
| `plan-web-frontend-minimal-core-2026-10-29.md` | 用户已拍板 = **Vue3**（2026-10-29），同日采纳 §11.3 三项；§12 六条订正已改入正文、两条待拍板同日已答 ⇒ **PR-0 已无待拍板项，开工仍等用户点头**（本索引不代认“开工”）；2026-10-30 用户实答 = **暂不开工，先只看工单拆解**，已写进该文开头的「开工授权状态」行；同日又追加一条**视觉层需求**，已登记为该文 **§13**；**同日第二批：§13.1 那份设计方案已产出（= 下面那行视觉件）但仍待批**，故 §0 标题那句「决策完备」的射程**仍不含**视觉格（三道门槛：决策完备 ≠ 规范已批 ≠ 开工授权）；§13.4 那三条随动义务已履行，逐条表在 §13.4 末尾。**次日第六批（10-31）三行随动已进 §13.4 末尾**，且 §8.1 那句「每刀 < 400 行」被本批体量实测**推翻**（三刀实取 825 / 644 / 1600+ 行，刀③ 含登记本行自身的文字故按量级读，两个处置选项待拍板）；**次日第七批（10-31）又在 §13.4 末尾加六行**（三口逐口实测 / V4 通道重定性 / 一屏读完只剩 A / 字体读数自证 / 体量三刀现取 / 射程与三门）。⚠ 本索引那句「加五行」写下时确实只有五行，第六行（体量三刀）随后才补 ⇒ **这类「本批共加了 N 行」的计数会被本批自己的后续编辑推漂**，第七批起新增段一律改指 §14.7 附行而不抄数并在 §12 那段过期陈述下补了一条**缺失已久的快照指针**（它原写「零 `web/` 文件、A1–A10 一条读数未取」而没有任何过期标记，从第五批起已失效）；§8.1 体量表本批已按现取重填（**引用前必须再重取，这类数会被登记它自己的文字推动**）；**次日第八批（10-31）又在 §13.4 末尾加六行**（① 三口改 `fail.push` + 明示跳过 / ② 措辞落地 / ⑤ 判据原文改形 / ③ 体量定案 + 分支 (a) 已批 / 一次探针自伤自纠 / 射程与三门），并把四项待拍板**全部收起** ⇒ 本节那句「两项待拍板」的在册项从第八批起要读成「已定案待执行」；⚠ 第八批**动了一件 POC 代码**（门禁脚本），所以该件末尾那句「零产品代码」只对其前各批成立 | 10-31 | 11 |
| `plan-web-visual-design-2026-10-30.md` | **设计方案（待用户点头）**——工程件 §13.1 六格的答卷，全部落成具体值（三层令牌 + 实算对比度色值表、12 类事件分色不写死数、断点/三态、**六个**默认值可推翻）。⚠ **同日第五批（POC 反写）三处形态订正已进正文**：① §2.1 从「三栏 + 灯阵在第三栏」拆为**两个视图**（对话页两栏 + `/health` 灯阵独立页，用户拍板）。这条订正的性质是**原判断不是错的，是放错了页面**：3 列 × 260px 地板在 372.8px 的 `1fr` 轨道物理不成立（需 796px），移到容器 1328.80px 的独立页后实测 4 列 × 319.80px、无溢出无断行；② §2.2 把「徽标只走图形通道」从规则升级为**带算式的判据**（族色上文字 3.25/4.25 < 4.5；tint 底版上次级文本 4.14）；③ §2.3 状态点从三档扩为**四档形状**，并记下「半径差 1px = 边长 10% 不算不同形状」（**推翻本件上一版自己的修法**）。**第四批那两条证伪原样有效**（色板已在蓝相带、不得再提「加微染」；分层不靠底色差而是两主题通用），§4 六个参照**已全部取证**（第三批补 Jaeger/Langfuse、第四批加 VitePress），但**取证只给「借什么」提供出处，不构成对本件的批准** —— 这条边界第五批同样适用且更要紧：**POC 跑了不等于本件批了**。新增 §11 = POC 实测反写的八条判断（F1–F8，每条带读数与落点），§7 逐道改为 V1/V2/V5/V7 有读数、V3/V6 到形状层、**V4 实拍未达（本机截图通道阻塞）**。**第五批不再是零产品代码**（样式三件 + 两个静态宿主页 + Node 门禁已在工作树，**未 `git add`**），但**后端目录 diff 仍 0 行**、§1.3 色值表**依旧一个 hex 未改**；新增一个开工前置拍板项（「一屏读完 30 盏」仍不成立，差 506px，三个处置选项待定，见本件 §11 F1）。⚠ **第四批及之前那些「未建 `web/`、V1–V7 一条读数未取」的陈述已全部失效**，本索引逐条改写。**次日第六批（10-31）只动了判据形状与取证工具，未动一个样式值**：§6 反证表补四行（含一行**故意不成立的探针行**），断言 6 那句「读不到源就 fail」被实测**收窄**（三口仍走 throw ⇒ rc=1 但 stdout 全空，**rc 不是可分的读数**），§11 F8 从全称句改为逐口读数，§7 V1 状态段随动（断言 4 三子句已补格且判据加了子句维度）。本批新增两项待拍板（三口 throw 缺口的处置、三刀体量超限的处置），累加在册的那项（一屏读完 30 盏 A/B/C），**以及一条本批自曝的判据不同步**：V1 原文仍写「§6 反证表**六格**」而该表已多行——建议改成「全部行（行数以该表与脚本为准）」而不是换成另一个数，**待拍板，本批未动判据原文**。⚠ **次日第七批（10-31）只动随动文字与表形，未动一个样式值、未改一条判据原文**：§6 反证表把断言 4 原本挤在一行的两个子句**拆成逐子句成行**（方向是**补表**而不是削脚本）、探针行从推定改为**逐口实取**；§7 V1 行就地标出「六格」与实物不同步（仍不改）、**V4 行从「阻塞」改写为「通道已成立但本道仍未过」并给三条理由**；§8 补上**缺的第六批行**（随动表自己漏随动）与本行；§11 F1 补上真实视口下的 A/B/C 代价量化（**只剩 A 与现实一致**）、F8 从三口推定改为四口实测。逐口与逐档读数在取证件 **§14**。⚠ **次日第八批（10-31）是四项拍板落地批**：头部那行末次改为第八批、§8 补第八批行、§2.1 与 §11 F1 的「一屏读完」按② 改为「一页内读完、允许滚动」（**仍一个样式值未改**）、§6 反证表原探针行按① 翻面为正常反证格（行保留不删、判据扩成三段）、§7 的 V1/V4 **判据原文**按⑤ 改为不抄数形状（**方向是加严**：旧措辞下的「六格全过」在新措辞下不自动成立）。逐口坐标与本批自犯表在取证件 **§15** | 10-31 | 8 |
| `docs/operations/evidence/2026-10-30-web-visual-references/readings.md` | 证据记录（**已验证**档，只到「外部读数与公式实算」这一层）：字体许可与体量、`@ibm/plex` 整包否决依据、Radix `src/` 目录形状、`console.html` 现状复读、**对比度脚本全文 + 92 行输出**（含探针自身错的实踩）、**§10 本批自查读数**（后端目录 diff = 0 行、四道门禁 rc=0，并写明 **`check_doc_sync.py` 不扫 `docs/` 下的路径引用** ⇒ 它的绿不能当作「本批互指路径已证」；引用边靠就地自查核，顺带登记两处既有悬空引用）。✅ §7 Jaeger/Langfuse **已取证**（同日第三批补跑，`gh api` 现取；未推翻设计值、补强五条）。✅ **§11 同日第四批（C 路）**：Radix 四张中性 12 档数值表 + VitePress 令牌/排版件实取（两仓都现取为 **MIT**）+ 中性色成族性与候选替换重算；**两条证伪**在此（§11.4.1 加微染建议作废 / §11.4.2 整族照搬会塌 SC 1.4.11：Radix dark slate8 = **2.58 < 3.0**），§11.6 是设计件落点逐行清单。✅ **§12 同日第五批（POC 落地 + 拆页 + 文档回写）**：八道门禁逐值 + 10 格变异表 + 浏览器两页 DOM/computedStyle 全读数（栏宽比值、30 卡列宽、scrollHeight 差、四档半径钳制算式）。⚠ **本节的诚实口径**：上一轮记的「400px 档横向溢出 834 > 400」**本批之前不在任何入库文件里**（可复跑取证 = `git grep -n 834 HEAD`，仅命中一条无关的提交号子串），故 §12 是**首次登记一个未入库的错误读数**并给出对照实验证伪过程；V4 实拍在本机**未达（阻塞）**，本件不得被读成「V 系列已过」；**§12.11 是分支模型的取证读数（八行表，命令逐字可复跑），方案本体在工单件 §8.1**。**✅ §13 次日第六批（10-31）**：断言 4 三个子句逐子句补格的读数（含脚本自己派生的计数行，不手数）+ **一次射程边界的实测**：同一个 rc=1 下，fail 口有可读失败清单、throw 口 stdout 全空只有栈 ⇒ 本仓库所有仅在 rc 上成立的陈述都被这一格削弱了一级（§13.3）。⚠ 本批**只登记未修**（改 throw 属开新方向），V4 实拍仍阻塞，全量终值在 **§13.6**。✅ **次日第七批（10-31）新建 §14**：三口 throw 逐口实取（含 verbatim Error 文本与正对照，**变异只打在镜像树副本上**、后端 diff 仍 0）+ **V4 实拍通道重定性**（14 张 PNG、页面异常 0、窄档无横向滚动、四档形状真图可辨）+ **一屏读完的 A/B/C 逐档代价量化**（结论：B/C 被证伪）+ **字体读数的自我证伪**（`document.fonts.check` 无判别力，改用平台字体逐节点实取）+ Node 24 解析坑的最小复现 + 十道门禁终值在 **§14.7**。⚠ §13.6 那张终值表自本批起是**历史快照**（已挂指针）。✅ **次日第八批（10-31）新建 §15**（四项拍板落地的取证）：三口 throw→`fail.push` 的逐口坐标与三条实现事实、十六格变异逐字表、镜像树 4/4 与一次 **R1 反证**（只换出口不加跳过会比原 throw 更危险：派生集静默缩小且报出方向相反的诊断）、② 的七处措辞清单、③ 的体量定案与三条复审触发条件、⑤ 的「加严非放宽」定性、八道 + 样式两道 + 形状复扫的终跑逐值（§15.9）、**本批自犯表**（§15.10，含两次栽在探针自身：形近清理集填错码点的空转「修复」与一支只读探针的死循环写出 300MB）、三刀提交台账（§15.12，**未填完前本件不得被读成「第八批已执行」**）| 10-31 | 9 |
| `plan-frontend-stack-selection-2026-10-27.md` | **已拍板（2026-10-29）——终态栈 = Vue3**；拍板范围**仅栈一项**；§8 三轮判据与决策日志不得因已拍板而删 | 10-29 | 12 |
| `plan-revert-checkpoint-integrity-2026-10-29.md` | **Proposed（待拍板）**，§7 六项未答 ⇒ 只阻塞 **PR-3**；PR-0/1/2/4 不受该阻塞影响 | 10-29 | 9 |

> **提及数口径**（2026-10-30 现取，命令 `(git grep -o --untracked -- "<令牌>" | Measure-Object).Count`；取证件那一行按**目录名** `2026-10-30-web-visual-references` 取，因为 `readings.md` 是 14 个取证目录共用的文件名、不具指认力）：视觉件 **8**、取证件 **9**、工程件 **11**。⚠ 两个条件必须一起读：① 全部**带 `--untracked`**（本批三件均未提交，不带这个开关会把“没扫”读成“没有”——工程件 §0.3 那族坑）；② 计数**含引用方自身与本索引行**（取证件 §10 那段自查里又写了两个文件名，那一次编辑就把三个数从 5/7/9 推到 8/9/11）⇒ 它是**当前工作树的快照**，不是常量；合入后还会再动。只作相对热度，不作“仍在用”的证据（口径本体见上面 §3 末那句）。⚠ **同日第三批（补参照取证）已逐字复跑一遍**，三个数仍是 8/9/11，但**构成变了**（视觉件那 8 次里取证件从 2 涨到 4、而顶层索引那一次没动）⇒ “数值相同”不等于“账面相同”，复跑读数与过闸门禁见取证件 **§10.1**。⚠ **同日第四批（C 路取证 + 两条证伪）又逐字复跑一遍**：三个数仍是 **8/9/11**，且这次**连构成也没变**（视觉件那 8 次仍是「取证件 4 / 工单件 3 / 本索引 1」）——因为写复跑台账时刻意**不在段落里重复文件名、也不新增任何 docs 下的路径引用**，于是引用边三值与第三批逐字相同（本批新增 0 条引用边）。这正是上一条那个坑的**可控形态**：计数会跟着文字走，所以记读数的那一段就不该再写文件名。同时门禁面从**六道扩到八道**（提及数入表 + 新增一道「表格完整性」，专防上一批实踩的「删掉行首竖线把表塌成散文」），八道逐值与台账在取证件 **§10.2**。⚠ **同日第五批（POC 落地 + 拆页 + 四份文档回写）又逐字复跑一遍**，并把台账扩到**十道**（原八道 + 样式层自己的两道：`node web/scripts/check-tokens.mjs` 与 `node .tmp-scratch/ap-visual/mutate-v1.mjs`）。这一批**不再能拿「三值逐字不动」自证** —— 拆页与文档回写往 `web/` 里放了七条未跟踪文件，所以账面形状从「全零」换成一对联合判据：**后端目录 diff = 0 行 且 非 docs 改动只含 `web/` 下的条目**。逐道读数与差值定性在取证件 **§12**。⚠ **次日第六批（10-31，补断言 4 子句格 + 一次射程实测）又逐字复跑一遍**：门面仍是**十道**（本批未新增门禁，只扩了变异工具的判据维度），但这一批把「不抄数」从口径变成工具行为：**本批新增的陈述里不再写变异格数与反证表行数**（AGENTS.md《验证策略》那条「条数以脚本为准」以前只在台账里被引用，本批起本索引的新增段也守它）；上面那些历史行里的旧数（如「10 格」）**故意保留不追改** —— 它们是各批当时的快照，改了就拿历史形状冒充现值。第六批逐格读数与全量终值在取证件 **§13.2 / §13.6**。⚠ **次日第七批（10-31，逐口实测 + 实拍通道成立）又逐字复跑一遍**：门面仍是**十道**（本批未新增门禁，只新增 gitignored 的取证 harness —— **逐支清单与创建时刻在取证件 §14.7 附行，本行不抄数**：本批一度写过「四支」，那是当时只建了四支时的快照，随后又建了若干支，抄数就会被自己的后续动作推漂，现已改为指向清单），三值仍为 **8 / 9 / 11**，且**构成也未动**——写本批那五处随动时刻意**不重复文件名、不新增任何反引包住的 docs 路径**（上一批靠这条口径把引用边钉在 139 不动，本批同法）：本批最差点踩到的一次是三口实测那两行——它们要引两个后端契约文件的路径才能说清「改的是哪一层的 class 头」，写成反引号就每人 +1 条边；处置是**只留中文描述 + 不带反引号的普通文本**（如「shared-schemas 侧 / agent_server 侧」）。⇒ 复跑实取：total 仍 **139** / unique 仍 **69** / unresolved 仍 **5**，BAD 五条同旧集 —— **本批新增 0 条引用边，没踩进去**（上一版本行曾误写「本批真的踩了一次」，复跑当场自证为假，已改；拿没跑过的数写「我踩了坑」与拿没跑过的数写「我过了」是同一种错）。第七批逐道终值在取证件 **§14.7**。⚠ **次日第八批（10-31，四项拍板落地）又逐字复跑一遍**：门面仍是**十道**（本批未新增门禁，只把门禁的一个**失败出口形状**改了：三口 `throw` → `fail.push` + 读不到源即明示跳过双向比较），取证 harness 多了几支但全住 gitignored（**逐支清单在取证件 §15.11 附行，本行不抄支数**）。引用边三值本批**没守住「逐字不动」** —— 新增的 §15 是一整节台账，它自己的文字就把边推了（上一批那条「写读数的那一段就不该再写文件名」的口径只对本批**新增的不带反引的普通文本**成立，而 §15 要引门禁脚本与样式文件的真实路径才能说清「改的是哪一层」）。⇒ 本批不在这段里抄那三个数（它们会被 §15.9 的末轮再推一次），**逐轮实取值与差值定性都在取证件 §15.9**；要拿这三个数当约束，先复跑。

## 4. 证据与历史层（留档，不外引、不改写）

- `docs/operations/evidence/` — **14 个日期目录**（2026-10-30 现取，命令 `Get-ChildItem docs/operations/evidence -Directory`；其中 13 个已入库、1 个是本批新增待提交），**每份一个 `readings.md`**。这个数字在 2026-10-15 写的是 6 —— 这类计数不补约定就会漂，所以取数命令就写在旁边。**每份的读数只绑定当时的 Pod `GIT_REV`**，换 rev 后须复跑，不得当现值引用。留档件是否入库由每次处置单独定：`2026-10-14-3node-deployment` 的原始 stdout（`raw.txt`）已于 2026-10-15 按需清除，回看用 `git show da96d870:docs/operations/evidence/2026-10-14-3node-deployment/raw.txt`，机侧另有一份在 `126:/tmp/inv-out.txt`（**清掉它就两处皆无**）。
- `docs/architecture/overview.html`（11 KB，09-23）— `docs/` 里唯一非 md 的架构产物，无入站引用；它不会被 `check_doc_sync.py` 覆盖，改动架构文档时不会有人提醒你同步它。
- `docs/analysis/2026-09-21/` — 9 份（`INDEX.md` / `PRIORS.md` / `PROMPT.md` / `00`~`05`）。该目录自带 `INDEX.md`，本索引不重复其内容；`02-debt-diagnosis.md` 提及 17 次，是这批里唯一仍被大量引用的。
- `docs/reviews/` — 2 份评审件（09-23，均已在 2026-10-15 补「后续处置」行）：对骨架方案的否定**已被采纳**；`review-v3-vs-skeleton-comparison` 给 V3 的第一条待补强**已按原文落实**（`agent-execution-platform.md` 第 35 行「与 8 层总纲的映射」），第二条（§27 目录逐行核对）**未核**，不得当已闭环。`docs/research/` — 4 份调研（08-22 ~ 09-25，其中 `deepseek-harness-discussions-analysis.md`、`code-agent-borrowable-features.md` 零提及）。
- `docs/tech-debt/` — 2 份：`tech-debt-audit-2026-09-22.md`（管「识别」）与 `tech-debt-hardcoded-logic.md`。与 `agent-harness-capability-map.md`（管现状）、`docs/TODO.md`（管排期）三套台账互不联动，判「会不会修」必须 grep TODO。
- `docs/handoff-2026-08-21.md`、`docs/fix-exhibition-agent-review-issues.md` — 交接与专项修复件，日期即封存。
- `docs/adr/0003-dual-db-driver.md`、`docs/ha/ha-durable-execution.md`、`docs/operations/deployment.md` 等 08-22 旧件：仍可能被现网事实推翻，引用前先在 §3 找有没有更晚的同主题 plan。

## 5. 新文档必须带的状态行（这次问题的根因）

71 篇 plan 正文里只有 29 篇开头有可辨状态行 ⇒ 没人能判断哪篇作数。今后 `docs/plans/` 新增一律在标题下第二行写：

```markdown
> 状态：<未拍板 | 已拍板待施工 | 施工中 | 已落地(<commit 或 PR>) | 已被 <文件路径> 取代 | 仅存档（结论已回写至 <文件>）> ｜ 依据：<代码/测试/命令实测的一条可复跑证据> ｜ 回写：落地后必须回来改本行
```

三条配套规则：① 结论落到活文档后就地改状态行为「仅存档 + 回写去处」，不要留一篇"看起来还待办"的旧稿；② 同一缺陷只留一篇主文，其余在状态行写「已被 X 取代」；③ 复选框只在**该文件既有范式是翻勾**时翻，且翻勾必须在行内写依据 + 声明块内计数口径（例：`plan-tech-debt-cleanup-2026-09-22.md` T0.2 块标题写「6 项」而实列 12 个复选框）。

## 6. 本轮没做的事

- **未移动、未删除任何文件**。2026-10-15 做过一次**内容合并**（合并 A：`runtime-analysis-overview.md` 的六块内容并入 `runtime-self-build-analysis.md`，源文件保留降级为寻址页）；`docs/plans/` 零提及的 9 篇一律保留。移动会改引用路径，`check_doc_sync.py` 只校验 AGENTS.md / ARCHITECTURE.md / README.md 三篇，它绿不代表其余 docs 的引用没断。
- **「未标」不等于「已了结」**：判"有没有状态行"的口径 = `head -25 <文件> | grep -qE "状态[^。；]{0,14}[:：]"`，实测 **42 命中 / 29 未命中**（71 篇 md 中）。**2026-10-16 重测 = 82 篇 / 52 命中 / 30 未命中**（**这两次是手测，分母口径不稳**：71 → 82 的差来自有没有把 docs/plans/README.md（此路径从未入库，见本条末的 2026-11-01 订正）与嵌套目录算进去。同日已收敛为脚本口径，判据与本节原文一致且把"排除 README"钉进代码：`uv run python scripts/evidence/recount_plan_status_lines.py`，2026-10-16 读数 = **分母 76 / 命中 47 / 未命中 29 / 真待补 28**（现值见顶部现状行）；（分母随新 plan 入库增长；§7 那份清单原 29 篇中 28 篇仍缺（`m5-semantic-cache-plan.md` 已于 2026-10-25 补状态注记），新增的 1 篇是 docs/plans/README.md（同上订正），属目录索引不是 plan，不计入待补工作面）。**2026-11-01 订正（只收引用形状，不改上面任何历史数字）**：本条两处提到的 docs/plans/README.md **从未进过版本控制** —— `git ls-files` 限定该路径为 0 行，`git log --all` 的新增 / 删除 / 总历史三条读数全为 0；docs/plans 下唯一 tracked 的索引 README 是 `docs/plans/archive/README.md`，与重算脚本规则 1 所排除的「同目录顶层那个 README.md」不是同一个对象。⇒ 「新增的 1 篇」到底指什么，现有证据无法复原，所以本条**只拆掉那对会让人误读成真实路径的反引号**（反引号 = 承诺按仓库根能解到），71 → 82 与 29 → 28 那串历史读数**原样保留**。同名假路径在 `scripts/evidence/recount_plan_status_lines.py` 的 docstring 里还有一处，属后端目录 ⇒ 前端 POC 批次以「后端 diff 为 0 行」为硬判据，**本批故意未动**，已登记为在册欠项（随后端批处理）。定性与取证读数见 `docs/operations/evidence/2026-10-30-web-visual-references/readings.md` §17.6。⚠️ 这个口径会漏掉「状态订正（2026-10-15 补）：」这类冒号前超过 14 字的写法，今天有两篇被它漏计（含 `p2-bucket-b-reduction-findings`），所以 **29 是上界不是精确值**；名单见 §7。
- 本索引自身的状态列是**摘录**，不是我对每篇结论的重新核实。任何一篇的数字要拿去对外用，仍按原文件的取证口径复核。

## 7. 待补状态行清单（2026-10-16 批次 ｜ 2026-10-27 复核：以下 27 篇仍缺；`m5-semantic-cache-plan.md` 已补状态注记故移出，另有 15 篇 10-18～10-21 新建未登记）

按 §6 命令在 2026-10-16 实测 29 篇未命中，其中 `p2-bucket-b-reduction-findings-2026-09-24.md` 是口径漏计（它写的是「状态订正（2026-10-15 补）：」，冒号前 18 字超出 14 字窗口，实际**已补**）⇒ 当时真待补 28 篇。**2026-10-27 复核**：脚本现读 94 篇 / 51 命中 / 43 未命中，其中 1 篇口径漏计 ⇒ 真待补 42 篇；下方 27 篇经同一判据复跑**仍全部未命中**，余额 15 篇均为 10-18～10-21 新建（如 `appendix-open-source-text2sql-benchmark-2026-10-18.md`、`plan-platform-tenant-workspace-identity-2026-10-18.md`），本批不逐篇展开——按口径未命中不等于该补状态行，需先读正文定性。

- `arch-audit-2026-09-24.md`
- `dep-security-accepted-risks-2026-09-25.md`
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
