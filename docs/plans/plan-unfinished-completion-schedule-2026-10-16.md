# 排期：未完成计划的收口计划与截止完成日期（2026-10-16）

> 状态：**现行执行排期**（本文件只做「排期 + 已核实进度 + 需拍板清单」，不重复各 plan 的技术方案；技术方案仍以各 plan 为准）。
> 制定日期：2026-10-16 ｜ 分支：`chore/tech-debt-agentic-discovery-test-2026-10-15` ｜ **本批不部署**（夜间 126 关机）。
> 上游锚点：`plan-production-delivery-roadmap-2026-10-09.md`（计划窗口 **2026-10-09 ~ 2026-12-04**，合计 84 人/日，其中 **8 人/日「待环境」，按 roadmap 自身规则不可承诺日期**）。
> 口径纪律：本文所有「已完成」均以**代码 + 测试实跑**为据（逐条附提交号），不以文档状态行、不以复选框、不以口头汇总为据。

## 0. 截止完成日期（先给结论）

| 层 | 截止日 | 内容 | 可否承诺 |
|---|---|---|---|
| **阶段 0 收口** | **2026-10-16**（今天，即 roadmap 原定窗口末日） | 待办清单与代码对齐、逐条补证据 | ✅ **已收口（10/16）** |
| **阶段 1 平台收口（本排期主目标）** | **2026-10-30** | 下文 §2 表中「我可独立执行」各行 **+ §12 收口对账** | ✅ **本地可执行行与收口对账均已于 10/16 做完**（提前 14 天；对账原判 10/28–10/30）；剩「待环境」行（#4 真库拒绝用例、#8 根因再现）不可承诺日期 |
| **阶段 2 提前开工（§7）** | **2026-10-19**（#12 观测装配门禁） → 后续行另排 | 把阶段 2 中**不依赖 126/密钥/真库**的行前移，避免 10/17–10/30 空转 | ✅ 可（#12 判据本地可验） |
| **阶段 2 再前移（§8）** | **2026-10-16**（#16 脚本半，判据纯本地可验） | roadmap #16「未注入变量时脚本拒跑而非默连本机」 | ✅ **已完成（10/16）**；#16 另一半「新场景在真库通过」待环境，本行不闭合 |
| **阶段 2 再前移（§9）** | **2026-10-17**（#11 存在性半，原排期首日） | roadmap #11「6/6 覆盖；门禁生效；灰度开关有记录」中本地可验的部分 | 🔨 **提前一天完成（10/16）**：共享装配 2/6→4/6 + P13 门禁；fork 收敛与 enforce 取证分别转 §3 第 9 项与待环境 |
| **阶段 2 再前移（§10）** | **2026-10-16**（#21 判据=每项有书面结论，本地可交付） | roadmap #21 六项遗留逐项定性 + 据此清掉三处不实陈述 | ✅ **判据达成（10/16）**；四项剩余缺口转 §3 第 11–14 项待拍板，不随本行关闭 |
| **§16 判定复核（roadmap §四 七条）** | **2026-10-16**（截止=当日） | 七条标准逐条对码复取，产出「判定列现值 + 计数口径 + 复跑命令」 | ✅ **已完成（10/16）**：1 条下修（第 6 条 达标→部分达标）+ 4 条订正定性（1/3/4/5），新增 2 行开项进 §2、2 项待拍板进 §3 第 19–20 项（第 20 项由 §17 追加） |
| **§17 变更记录补齐（§四 第 7 条残口）** | **2026-10-16**（截止=当日） | `CHANGELOG.md` 补 10/10–10/16 未发布窗口节 | ✅ **已完成（10/16）**：120 个提交入窗口节、11 个锚点逐个核对、历史节零改动（diff 16+/0−）；版本号 facet 实测无映射 ⇒ 转 §3 第 20 项 |
| **§19 exhibition env 模板门禁（#21 / P2-5）** | **2026-10-16**（截止=当日） | 给会展侧的「模板 ↔ 代码」一致加装自动检查（前缀折算口径） | ✅ **已完成（10/16）**：新增 3 条用例，四条变异全部击中；exhibition **368 → 371 passed**。**同批撤回一条我自己造出的假缺口**（前缀-blind 探针曾报"9 键缺失"）；`make eval` 复跑被执行权限层拦下，记为**待放行**，未绕过 |
| **§22 阶段 0 #2 完成证据格式（roadmap 阶段0）** | **2026-10-16**（截止=当日） | 「无统一的完成证据格式」这条自 10-09 开着的阶段 0 行 | ✅ **已闭合（10/16）**：`docs/operations/evidence-format.md` 入库（五字段 / 三禁令 / 三档强度 / 变异反证表），§6 逐条对照六处既有用到的读数；入口挂 AGENTS.md + testing-playbook ⇒ **roadmap 阶段 0 小计 3 → 剩余 1**（#3 属外部条件，保持开项） |
| **§24 错分类的机械活回收（#21 收尾）** | **2026-10-16**（截止=当日） | 把「补模板」从「要不要建门禁」的待拍板捆綁里拆出来做完 | ✅ **已完成（10/16）**：federation +7 / KS +10（AST 实读取默认值 + `<- 文件:行` 溯源，密钥留空）+ `tests/governance/test_app_env_templates.py` 2 条；**口径订正**：真缺 17 而非登记的 61（active vs 提及 两种读法差出来的）；CI 等价根会话未重跑 ⇒ +2 属推断，已标注 |
| 阶段 2 / 阶段 3 | 11-13 / **12-04** | 归 roadmap，不由本排期重排 | 部分待环境 |
| 一期交付判定 | **2026-12-04** | roadmap §四 七条标准逐条判定 | — |

**一句话**：本轮排期的截止完成日期 = **2026-10-30**（对齐 roadmap 阶段 1 窗口），整体交付分界仍是 **12-04**；凡依赖 126 真库 / PR / CI / CodeQL 重扫者，**只登记不承诺日期**。阶段 1 的本地可执行部分已提前清空，故自 10/17 起按 §7 前移阶段 2 的本地可行项。

## 1. 已核实完成（证据，非账面）

| roadmap 行 | 判据 | 实测状态 | 证据 |
|---|---|---|---|
| 阶段1 #5「4 个模块主流程未调用」 | 每模块有测试与独立提交 | **4/4 已接线**（state_migration / execution_recovery / payload_externalization / human_task） | `c49ee2dd` `4a7c662e` `6bf15287`；`packages/agent-runtime/tests/test_human_task_wiring.py`(5) + `applications/agent_server/tests/test_human_task_api.py`(12) |
| 阶段1 #4（代码面子项）防覆盖 fence | 保护覆盖 5/5 | **代码面 5/5**；真库拒绝用例仍待环境 | `68a44290`；`packages/agent-runtime/tests/test_receipt_generation_fencing.py` |
| 阶段1 #6 健康检查报四部件 | 开关跟随断言 | 已完成（`18b6954`）+ 残差补强已做 | `d31f247e`（`cost_governance`/`forensic`「输入变则值必变」） |
| P0-4 桶 A（盲捕获安全窄化） | §3 逐站点核对 | **8 站点全部已落地**（此前该 plan 自记「不作结论，需逐个核对」，本批已核对） | `milvus_utils.py:68` `(ValueError, TypeError)`；`node_pdf_to_md.py:134/156/239/339`；`benchmark/locustfile.py:46` `(OSError, ValueError)`；`tests/unit/test_tracing.py:35/41` + `test_security_guards.py:47` `ImportError` |
| T2.2 item5 | 行为等价 + 零回归 | 已落地 | `b35f35a`；federation **176 passed** |
| T2.3（8 项依赖配置） | 逐项对码 | 已重新对码 + 2 项本批落地 | `af2f980`；exhibition **357 passed** |
| 阶段0 文档状态行 | 每条状态有代码/测试依据 | 7 篇漂移状态行已订正 | `06c1b1b` `c05ba0a` `1640f38` `d08a751` `a5eacd4` `75fdabe` |

> **订正一条我上一轮的错判**：P0-4 与 tech-debt T2.2/T2.3 曾被我为「待拍板 / 高风险」而整体归为不可推进。实读后：P0-4 **2026-09-24 已由用户逐站核查批准**（范围=桶 A），T2.3 的多数项是包改名导致的 moot 而非决策悬置。⇒ 教训：判「受阻」前须读方案本体，不能只看状态行或凭印象。

## 2. 剩余工作排期（10/17 → 10/30）

| 日期 | 项 | 来源 | 影响面 | 验收判据 | 归属 |
|---|---|---|---|---|---|
| 10/17–10/18 | **#5 残口：订正 `execution_recovery.py:11` 陈旧 docstring**（仍写「payload_externalization / human_task 仍未接线」，与本批代码矛盾），并加「禁止再退化为孤岛」的装配面自动检查 | roadmap #5 判据「全仓未接线标注归零」 | 仅 docstring + 1 个门禁测试 | 该模块 docstring 不再声称未接线；`test_v3_wiring_assembly.py` 增断言且红→绿 | ✅ **提前完成（10/16）**：docstring 已订正为「已接线，接线 ≠ 默认启用」；新增 5 条护栏（4 模块装配锚点 parametrize + 1 条「已转正模块不得自称未接线」文档护栏），**并已反证护栏非空转**——43 个 agent_runtime 模块中 26 个被 main.py 引用（4/4 命中）、17 个正确报缺（`cache`/`circuit_breaker`/`effect_contract`/`forensic`…），⇒ 锚点消失即 fail。`agent_server` **122 passed**、ruff 绿 |
| 10/18 | **#D7 桶 A 记账闭合 + 残余定性**：本批实测 `git grep 'noqa: BLE001'` = **37 处**（集中在 `knowledge-service/eval/*.py`、`agent_server/main.py:131`），与 P0-4 §5 硬判据「=0」不符 ⇒ 逐处判定「属 M2 已放弃的逐点 noqa（应迁入整包基线）」还是「桶 C 承重点（应保留）」并写结论 | P0-4 §5 / TODO D7 | 只动 pyproject 基线 + 注释 | `ruff check .` 全绿；§5 判据被逐处定性（不粉饰为 0） | ✅ **完成（10/16），结论与原判据相反**：**不迁基线**——实测两种豁免强度不同（新加 `except Exception` 在「仅逐点 noqa」文件里 **ruff 报错**；在「已入 per-file-ignores」文件里 **ruff 放行**）⇒ 逐点 noqa 是**行级精确棘轮**，整包基线是**全文件永久 blanket 豁免**。为凑 0 而迁移 = 把 13 个文件降级并丢掉每处理由注释，正是本方案桶 B 已否决的「为降指标动手」。改做**增防护**的两件事：① 补齐 9 处无理由 noqa ⇒ 裸标 **0/36**；② 删 1 处 **vestigial**（`identity.py:220` 捕的是具体类型 `jwt.PyJWTError`，BLE001 本就不触发，stdin 探针证明去掉仍全绿）⇒ **37→36 真实降量**。§5 判据建议改为「裸标=0 + 基线文件不得补逐点 noqa + 周期重扫 vestigial」，**此项待你认可**（改的是验收判据本身） |
| 10/19–10/21 | **#10 数据可信度默认值改「待确认」**：无标注响应不得按「完整可信」输出；缺标注则拒绝接入 | roadmap #10 | exhibition 侧 `data_readiness` 消费链 | 造一条无标注响应 ⇒ 输出显示「待确认」（新增用例） | ✅ **提前完成（10/16，两句都做）**：① 运行侧 `_map_readiness` 有**两处** fail-open（`level is None` 与函数末尾兜底 `return READY`），现均判 `UNCONFIRMED`，`Readiness` 加 `UNCONFIRMED`，输出带「数据可信度待确认」warning；② 接入侧 `skill_router` 门禁只拦 `SYNTHETIC`，未标注者落 `UNKNOWN` ⇒ **自动放行**，现生产档 `UNKNOWN` 亦拒。行为差分实测：仅 `None`/未知 level/空串 3 项由 READY→UNCONFIRMED，`complete`/`synthetic`/`partial`/`pending` 4 项不变。新增 11 条断言，exhibition **368 passed**。**遗留（需业务侧标注，非我可判定）**：catalog 48 接口中 `create_lead`/`delete_lead`/`confirm_lead`/`reject_lead` **恰是 4 个写操作且无 readiness** ⇒ 生产档现被拒；上线前须由业务方补标注（我不替它们猜值）。DEMO/DEV 档不受影响 |
| 10/22–10/27 | **#7 对外数据格式补健康检查字段与界面所需结构**（**先做消费方影响评估**，不得静默改下游解析形状） | roadmap #7 | shared-schemas / 下游前端与网关 | 跨服务一致性测试 + 打分测试均不破坏下游 | 🔨 **拆两半交付（10/16）**：**「不破坏下游」的那半已做**——新增 `tests/test_health_contract_consistency.py` 8 条（钉共享契约服务不得退回裸 dict / 遗留约定逐项登记且**登记失实也报红** / **禁第 4 套 `status` 字面值**，用 AST 只取 `/health` 路由自身返回）。**「统一形状」的那半转 §3 第 6 项待拍板**：实测三套约定并存（`healthy` 枚举 / `"ok"` / `{"ok":true}`），统一要改 3 个服务的线上响应值并牵动 knowledge-service `/health/ready` 的 503 就绪探针语义 ⇒ 按 AGENTS.md「边界」条不擅动。评估全文见 §6 |
| 10/22–10/27 | **#4 重复实现去重复核**：roadmap 记「同名任务回执存储有两份实现、接线用的是无保护那份」。本批 `git grep 'class .*Receipt.*Store'` **未命中**⇒ 疑已合并；须以实读确认「同名实现只剩一处」是否成立 | roadmap #4 判据 | 若仍在则删重复一份 | 判据「同名实现只剩一处」有实读证据 | ✅ **提前完成（10/16）**：**上排的「疑已合并」是错的**——错在用了猜名字的 grep（`Receipt.*Store`），而那两份实际叫 `PgAwaitableTaskStore`，模式不含 "Receipt" 故 0 命中（假阴性）。改用**跨包重复类名扫描**才定位到：`awaitable_task_pg.py:24`（已带 fence，生产接线，`main.py:435`）与 `execution_state_pg.py:114`（**无 fence**：`save` 的 INSERT 只写 15 列、`generation` 留空、无 WHERE 守卫）。后者**零 import**（全仓只从该模块取 `PgExecutionStatusStore`）⇒ 死副本，已删。**危险不在冗余而在 import 点**：`execution_state_pg` 是「Pg 存储」的自然取用处，从那儿 import 同名类会静默丢掉 ``68a44290`` 的 fence。唯一实现由新用例**双向**钉住（无第二份 + 留下那份必须带 fence，防删错方向），并反证删除前必红。⇒ **#4 判据「同名实现只剩一处」现已成立**；其余判据（真库两类拒绝用例）仍待环境。**方法教训**：判「是否还有重复实现」不能靠猜类名的 grep，要按「重复定义」这一结构事实扫描 |
| 10/16（再前移，见 §8） | **#16 第一半：强杀脚本去掉本机默认 DSN**（判据「未注入变量时脚本拒跑而非默连本机」） | roadmap #16 | 仅 `scripts/ha_real_kill_verify.py` + 1 个新门禁测试，不改任何产品链路 | 未注入即非零退出且点名变量；连接前即拒跑；6 处变异反证 | ✅ **完成（10/16）**：默认值（含内嵌凭证）删除，缺失 ⇒ 退出码 4；目标库以脱敏形式进日志；`tests/test_ha_kill_script_gate.py` 5 条 + 变异反证；CI 不受影响（`ha.yml` 已注入该变量）。**第二半待环境** |
| 10/17（再前移，见 §9） | **#11 第一半：身份门卫装配覆盖 + P13 存在性门禁**（判据「6/6 覆盖；门禁生效；灰度开关有记录」中本地可验的部分） | roadmap #11 | 新模块 1 + 两服务装配点与各 1 处依赖声明 + lint 新规则（含 L-5/P13 枚举合并） | 6/6 有装配点且归属可审计；注释掉即报红；两服务响应不变 | ✅ **提前完成（10/16）**：共享装配 2/6 → **4/6**（kefu、nl2sql 从零门卫接入 observe 档）；P13 归属表把另外 2 家**自带实现**记成在册债（收敛待拍板 §3 第 9 项）；顺带修掉验签器异常会变 500 的问题。门禁 5 条反证 + 真树变异两次。**enforce 生效待环境**，本行不闭合 |
| 10/28–10/30 | **阶段 1 收口对账**：逐条按 roadmap「怎么算改好」列复核 + 全量门禁（`ruff check .` / `check_doc_sync.py` / 相关 pytest session） | roadmap 阶段1 | 文档 | 每行有代码或测试依据；待环境行明确标注「标准环境已验证 / 多物理机待环境」 | ✅ **提前完成（10/16，见 §12）**：11 行逐条以命令重取证据（含 10 session 全量门禁 2912 passed / 16 skipped）；**并抓出我自己 4 处账面错数**（实现函数 17→18、agent_server 11→43 键、KS 8→13 项、以及一条已撤回的污染假设），其中「判据措辞欠账」一项等你定 |
| 10/17 | **§16 新登记：变更记录半边补齐**——为「未发布窗口」补一节 CHANGELOG（覆盖 2026-10-09 之后进入本分支祖先链的全部提交，rev 数见 §17 表），使 roadmap §四 第 7 条「变更记录与代码一致」有判据可依 | roadmap §四 第 7 条 / #1 收尾 | 仅 `CHANGELOG.md`，不改代码、不动历史条目 | 新节覆盖到本分支 tip（逐条可指回提交号）；历史节零改动；`check_doc_sync.py` 仍绿 | ✅ **完成（10/16，见 §17）**：新增「未发布窗口补记：2026-10-10 – 2026-10-16」一节，覆盖 120 个提交（main 79 + 本分支 41）、8 个批次、11 个提交锚点逐一 `git log -1` 核对；历史节零改动。**判据按 §17 的口径声明**：本节是「按批次聚合 + 可机械枚举的 rev 范围」，不声称逐提交转写 |
| 10/17 前出方案，实施待拍板 | **§16 新发现：标准 6 由「达标」下修**——`ForensicContext` 的 `external_inputs` / `external_task_receipts` / `effect_receipts` 三格生产零写入点，全仓唯一生产构造点只填 `model` + `planner_version` ⇒ 「每次回答可追溯数据来源」不成立 | roadmap §四 第 6 条 | agent-runtime 取证装配点 + planner 执行链 + 下游观测面 | 判据本身要先定（粒度/哈希口径/PII 边界/回执汇流方向四问，见 §3 第 19 项）；实施后 = 三格各有一处生产写入点 + 「输入变则值变」断言 | ⚠️ **转 §3 第 19 项待拍板**：设计决策 + 改的是每次回答都写的取证记录形状，按红线不擅自开工 |
| — | **待环境（只登记，不承诺日期）** | #4 真库两类拒绝用例、#8 KS 15 条报错根因 + 图谱重测、#16 第二半（双机接管+防覆盖+过载保护场景在真库通过）、V3 双实例物理故障转移、CodeQL B7b-4/5 重扫、env-var 126 部署脚本同步 | 需 126/PR/CI | roadmap §四第 2 条规则 | 环境解锁后 |

## 3. 需要用户拍板（**请在 10/20 前给方向，否则将阻塞 §2 后半**）

红线「所有代码优化/重构必须先制定方案」+ 我不替你做设计决策。以下 **21 行**（按本表条目计数，非按 plan 文件数）方案已就绪，卡在「选哪条路」而非「有没有路」：
**其中真待拍板 = 20 行** —— 第 1 项经 2026-10-16 对码作废（代码早已合入，见该行注），作废行的编号保留不复用；第 17 行按行计 1、内含 5 问（三份 ADR 各 §5）；第 19–21 项由 §16/§17/§20 对码新增。

1. ~~`plan-audit-operator-principal-2026-10-03.md` — 审计主体改造是否开工（现：方案已写、零代码）~~ **本项作废（2026-10-16 对码）**：
   代码早做完并合入了 —— `session_router.py:71` = `operator = server_tenant_id(settings.default_tenant_id)`、P12 门禁在 `lint_architecture.py`、
   治理用例在册、提交 `116d51b1` → PR #61 → merge `bb2b9a81`。**是我把 `docs/TODO.md` 的三段已完成追记漏读、照 plan 陈旧状态行登记成了待拍板**
   （plan 状态行已按证据订正）。真正未闭合的那条是**部署侧 `revert_audit.operator` 存量历史行取证**，属**待环境**（三通道不通），不是决策项 ⇒ 从本表移出、编号保留不复用（防 §3 他处「第 9/12 项」这类交叉引用错位）。
2. `plan-m11-exception-classification.md` — 状态 `Proposed`，接受 / 修改后再施工
3. `plan-router-keyword-gate-hides-corpus-2026-10-12.md` — 修法三选一
4. `plan-v3-phase-2-4-integration-2026-09-23.md` — v2 方案（含 6 项不变量）确认后施工
5. tech-debt 补充 4 — agentic bridge 默认开 vs 保留 opt-in 但补开启路径测试
6. **#7 对外 `/health` 三套约定是否统一**（评估结论见 §6）——统一到共享 `HealthStatus` 需改 exhibition/kefu/knowledge 的**线上响应值**，且 knowledge-service `/health/ready` 的 503 是就绪探针语义的一部分。本轮只交付不破坏下游的一致性测试 + 禁第 4 套护栏；统一与否请你定（选项：a 全统一到 `HealthResponse` / b 仅新增服务强制、存量保留并在看板侧做映射 / c 保留现状仅靠测试钉住不再扩散）。
7. **#12 追加**：是否把 `init_tracing` 移进 `build_api_app` 成为"构造保证不可漏接"。本轮把「统一装配」实现为**统一工厂 + L-5 存在性门禁**已满足判据「漏装即 CI 失败」；但把 init 放进工厂会与 agent_server 现有顺序约束冲突（其源码有「别挪回去」注释：Langfuse 客户端构造会抢全局 TracerProvider ⇒ `init_tracing` 必须早于模型构造），且工厂在 import 期被调用会引入 import 副作用。属架构取舍，请你定。
8. **取证脚本的 `127.0.0.1:18000` 默认值是否同样 fail-closed**（详见 §8 末段）：`deploy/observability/langfuse_proof.py`、`deploy/k8s/scripts/e2e_traceparent.sh` 与已修的强杀脚本同属「输出被当作现网证据」的一类，但它们的本机默认值是**运维本机 port-forward 的既定用法**，改动要连带重写 `docs/operations/env-126-inventory.md` / `deploy/k8s/VERIFICATION.md` 里的在册命令。选项：a 两个都改（一致性优先，附命令文档同步）/ b 只改 langfuse_proof 的提问模式（只读复核模式不需要 TARGET）/ c 都不改，靠手册声明。我倾向 a，但它改的是**你正在用来取证的命令的形状**，所以由你定。

9. **两套自带身份门卫是否收敛到共享实现**（§9 / `plan-identity-gate-6of6-2026-10-16.md` §5.1）：knowledge-service 的 `TenantHeaderMiddleware` 与 exhibition-agent 的 `X-Execution-Context`（**逐端点调用**、DEV 档刻意不验签）都在 126 上活着。P13 的归属表已把两家显式记成在册债，所以「6/6 覆盖」现在是一句**可审计**的话，而不是"都装了个门卫"。收敛会改两家的部署开关名与响应形状（KS 的 `/health/ready` 503 就绪语义牵连其中）⇒ 按 AGENTS.md「边界」条不擅动。选项：a 先收敛 KS，exhibition 的端点级覆盖另行处理 / b 两个一起收敛 / c 三套并存但 P13 归属表长期挂着（现状）。
10. **路由侧「自报租户」是否换成服务端断言**（§9 / 同方案 §5.2）：这才是 #11 的真正收口动作，但它让调用方**能观察到行为变化**（自报 `tenant_id` 不再被采信）。牵动 agent_server `/query` 的 9 处与 kefu 的 2 处；且 **nl2sql-service 的「租户隔离」目前没有定义**——其源码零 `tenant` 引用，契约里有 `tenant_id` 字段但从不读，所以得先回答"按什么隔离"（数据源？元知识库？结果集？）才谈得上验收。选项：a 先只定义 nl2sql 的租户语义、存量自报暂不动 / b 一并翻断言（要先审计前端与网关的取值来源）/ c 停在 observe 档，等二期接口签字后再动。

11. **WS 路径要不要接 admission 与背压**（§10 P2-3）：`/ws/{thread_id}` 被入口护栏**显式豁免**（`agent_federation/api/server.py:158` `exempt_paths=("/health", "/ws/")`），且逐条 `send_json` 无队列/水位（`:382-388`）。错误帧这一半已补（`:392-403`），但限流与背压要动的是**客户端能观察到的行为**（慢消费者会被暂停或断连），属对外语义决策。
12. **`.env.example` 剩余补齐范围与要不要做门禁**（§10 P2-5；**2026-10-16 已推进一半，做法见 §11**）：实测原写"agent_server 整份缺失、约 60 个键代码读而文档缺"，另有**观测两键"文档有而代码无"且自诞生起无人读取**（KS `KNOWLEDGE_SERVICE_NAME` / `KNOWLEDGE_TRACE_ENABLED`，2026-10-16 对码定性：`37d93427` 空改名，14 处出现/8 个文件，含 dated 记录正文与单测 `delenv`；已改用内核 `AGENT_CORE_*` 并钉桩 `test_env_example_observability_keys_are_read_by_code`）。
    **已完成**：① 观测两键按上面那句处置；② agent_server 的 **43 个**"代码读而模板缺"键已补进**根** `.env.example`（判据：它实际加载的是 CWD 那份，不是应用目录那份），并加齐全用例 `tests/governance/test_agent_server_env_template.py`（3 项变异验证均转红）。
    **待你定的只剩两件**：① 剩下 **61 项**（KS 13 / federation 47 / exhibition 1；**2026-10-16 §24 订正：这条被我错分类过 —— "补模板"是机械活、不该等拍板，已按 AST 实测补录 federation 7 / KS 10，所谓 61 是按 active 口径虚高的数；真正还欠你定的只剩下面 ② 那一件**口径与两个盲区见 §10 P2-5 ②）要不要补；② 要不要做**全仓双向门禁**（"模板键 ⇔ 代码读取"，需先解决共享层读取与 `env_prefix` 折算两个扫不到的面）。
    选项：a 补 61 项 + 建双向门禁 / b 只补 61 项、不建门禁（agent_server 那 43 项就是按这个形状做的）/ c 停在现状。**注**：本轮已把 KS 观测两键从"杜撰键"改判为"**文档化但无人读取的开关**"——危害不是文档噪音，而是照文档设值后静默不开。

13. **MinIO 初始化要不要翻成默认拒绝启动**（§10 P2-7）：上传路径已 fail-fast（`import_router.py:229-232`），但 `clients/minio_utils.py:12-51` 初始化仍是"记 error + 置 None"。翻了之后缺配置的部署从「能起但导入功能坏」变成「起不来」——这是**部署侧的可用性取舍**，且牵动 126 现网。顺带一条孤儿：`core/config.py:174-187` 的 `validate_credentials()` 全仓零调用方（要么接上要么删，我不擅自定）。
14. **文档口径的自动兜底要不要建**（§10 P2-6 (a)/(c)）：`check_doc_sync.py` 只核路径存在性与 session 数，核不出"门禁条数/覆盖率/状态行"这类**数字漂移**——本轮我自己就把 14→16 的口径破了又补。选项：a 让 check_doc_sync 增核「lint 条数三处一致」（把现值算出来比对，破口即红）/ b 维持人工收尾 / c 改为文档里不再写死数字、只写口径定义。 **本轮实测补充**：`check_doc_sync` 的判定面只有根三篇（`DOC_FILE_REF_DOCS`，`scripts/check_doc_sync.py:41`），`docs/README.md` 那份索引插了假路径也照样 0 警告 ⇒ 覆盖面比直觉窄，详见 §13.1。**§12 又添一例支持选 a/c**：收口对账重取时发现我写的"实现函数 17 个"其实应是 **18**（`check_*` 17 + `check()`），这种数只有跑一遍脚本才抓得住，人工收尾已连续两次漏。
15. **roadmap #5 的判据措辞要不要改写**（§12）：原文「全仓"未接线"标注数归零」**无法机械复核** —— 字面 `git grep "未接线"` 在当前树命中 **20 个文件**（CHANGELOG/plan 历史留档、`README.md:562` 讲的是另一个未接线面、eval spike 自述），而该行的真实意图是「已转正模块的 docstring 自述归零」（这半已达成并有 `test_v3_wiring_assembly.py` 18 条护栏）。选项：a 判据改写为「`agent_runtime/*` 已接线模块的头 docstring 无『未接线』自述」（可被那条文档护栏直接执行）/ b 保留原句并加口径注 / c 不动，留作人工解释。
16. **意图路由绕过统一 embedding 提供方**（`plan-intent-embedder-bypasses-provider-2026-10-10.md` §6）：本项**此前漏登记**——我按 §3 台账清点时没扫这份 plan，直到本轮清扫全部 plan 状态行才看到（属台账自己的缺口，不是这份 plan 的问题）。该 plan 明写「全部等拍板」，且带**现场运行证据**而非静态推断：§5 r12 在 `EMBEDDING_MODE=mock` 下 `POST /query` **260s 零字节**、服务端日志显示仍去 `huggingface.co` 取权重并重试 5 次；r13 设了 `HF_HUB_OFFLINE=1` 后同一请求 12.8s 完成 ⇒ 代价完全取决于那个开关，而 `/health` 的 `embedding_real` 读不到这条旁路。待你答两问：① 选 **A**（`classifier._embedder()` 改走内核 `get_embedder()`，与 RAG/记忆共用选型与 `EMBEDDING_REQUIRE_REAL` 护栏）/ **B**（只改 `/health` 描述并加 `intent_router_backend` 读数）/ **C**（本版明确宣告意图语义层未生效）；② 若选 A，mock 提供方下是「允许降级但必须报状态」还是「直接拒绝启动」。**这条决定的是要不要动请求路径，我按红线未动一行。**
17. **roadmap #24 三项悬置选型（本行按 §3 条目计数记 1 行，内含 5 问）**（§13 已交付三份决策记录，问题各写在其 §5）：
   `docs/adr/0008-auth-mode-selection.md` —— U1 入口静态 `API_KEY` 与"未配 key 即不校验"旁路要不要结构性关闭
   （A 把 `DEPLOY_ENFORCE_IDENTITY` 默认改 True / B 靠部署清单 + CI 校 / C 不动）、
   U2 要不要 key→主体 映射（ADR-0007 §7.1 已确认承载 ≥2 个真实外部租户 ⇒ 选"不映射"是否与那句矛盾，需你一句话定）、
   U3 `ExecutionContext` 是否整体迁 JWT（ADR-0007 §53 明写与本问合并决策，属**有意悬置**不是遗漏）；
   `docs/adr/0009-vector-store-selection.md` —— A 统一到 Milvus / B 统一到 pgvector / C 明确并存并加"禁止第三套"不变量；
   `docs/adr/0010-ui-stack-selection.md` —— A 扩只读控制台 / B 新建前端工程（须附框架与维护人）/ C 混合 + 重启条件。
   **这五问未答，我不动 `auth.py`、存储层、界面层任何一行。**
18. **ruff 的四族规则要不要纳入 `select`**（§15 D4 收尾后剩下的那一步）：`B008` / `B017` / `PERF102` / `RUF059` 现在挂在根 `ignore` 里，
   但它们**所属家族根本不在 `select = ["E4","E7","E9","F","I","BLE001","S110"]` 内** ⇒ 对 `ruff check .`（CI 门禁）恒为 0，是**死配置**；
   真实存量（`--isolated` 口径）分别是 **7 / 8 / 4 / 37**（合计 56）。选项：
   a 把 `B`（bugbear）纳入 select，同时**逐条判**——B008 的 7 处基本都是 FastAPI `Depends()` 写在默认参数位（官方推荐写法），需要配 per-file/全局豁免而非整族关掉；
   b 纳入 `PERF102`/`RUF059`（4 + 37 处，属可清的真实改进，但要一次性动 41 处）；
   c 维持现状（这四族只在 `make type` 的 `--select ALL` 下可见，不参与合入门禁）。
   **我没动它们**：纳入 select 属规则集扩容，按 AGENTS.md「框架/规则约束应是减错而非碍事」要逐族判，且一次会引出 56 条红 ⇒ 需你定方向。本轮只把**已确认零违规的 9 条死豁免删掉**（这是 D4 判据本身要求的事）。
19. **§16 下修标准 6 后引出的那一问：数据来源取证字段要不要在本窗口接线**（`ForensicContext.external_inputs` / `external_task_receipts` / `effect_receipts` 生产零写入点）。
   这三格不是"忘了填"：填什么要同时定 **① 取哪个粒度**（每次外部调用一条，还是每次回答一条汇总）、**② 哈希口径**（原文 sha256 / 引用 ID / 长度+前缀，涉及体积与"能否据哈希反查原文"）、
   **③ PII 与出域边界**（`external_inputs` 是"重要外部输入快照"，会展链路含客户线索，落哈希还是落引用直接牵动数据分级），**④ 回执是否单向从 `awaitable_task` 汇进取证记录**（现在两边都有落点、互不引用）。
   这四条是**设计决策**而非工程残料，且改的是每次回答都会写的取证记录形状（下游 = Jaeger/Langfuse 面与事后 divergence 诊断）⇒ 按红线我先不出方案、等你给方向。
   选项：a 本窗口做（我先出方案文档，你批了再编码，判据=三字段各有一个生产写入点 + 「输入变则 hash 变」断言）/ b 只登记为标准 6 的在册缺口、留到 11/14 阶段 3 / c 只接 `external_task_receipts`（回执已有现成落点、跨模块引用成本低），来源与副作用两格后置。
   **我未动 `forensic.py` 与任何 planner 执行链一行。**
20. **§四 第 7 条的第三个 facet「版本号」要不要建立对应关系**（§17 实测：三处版本面互不对应）。
   现值：根 `pyproject.toml:3` = `0.1.0`，`agent_federation` = `2.0.0`、`knowledge-service` = `1.1.0`，其余 6 处均 `0.1.0`；
   而仓内**存在** `v2.0.0` / `v3.0.0` 两个版本 tag（另有 3 个 `archive/*` ref），**没有任何书面文档说明 tag、包版本、现网 `GIT_REV` 三者怎么对应**。
   ⇒ 「版本号与代码一致」这句判据目前**无可核对的定义**：拿 semver 对，根包永远 `0.1.0`；拿 tag 对，tag 不指向任何 pyproject 值；拿部署面对，`deploy/k8s` 用的是 `GIT_REV` 而非版本。
   选项：a 宣布「本仓不使用 semver，唯一版本标识 = `GIT_REV`」并把 9 处 `version` 定为装饰性字段（写进 ARCHITECTURE，判据改成「`/health` 或启动日志必须报 rev」）；
   b 起一条真实发布线（根包 + tag 对齐，如 `v0.2.0`），后续每次交付打 tag；
   c 只对齐 federation/KS 两个非 `0.1.0` 的（它们大概率是历史发布遗留，需先查这两值是谁在什么时候为什么改的——我没查到书面依据）。
   **我未改任何 `version` 值、未打 tag、未删 tag**：这三者都属对外可声称的发布事实，按「不在本窗口部署/发布」的约束由你定。
21. **`make eval` 判分基准要不要跟着 F01 生产实现重取**（§20 查出，TODO §4 F01 的残差就在这里）。
   `evaluation.py` 的 positive 路径仍调内联 `_mock_scope_filter`，而它与生产实现 `enforce_scope_filter` **不等宽**：
   mock 对 `scope_type=PUBLIC` 的跨租户项**放行**，生产实现没有 PUBLIC 例外、且 `ctx.scopes` 非空时还要再收窄 ⇒ 换过去 golden 判分必然变（15 题基线要重取）。
   跨租户负样本路径早已跑生产代码（审计 P1-9 那批），所以这不是"接线缺失"，而是**要不要改评测语义**的决策。
   选项：a 换实现 + 重取基线（我先出方案，含逐题差分与新的 `--fail-below` 定值）/ b 保留 mock 但在评测输出里显式标"positive 路径为宽松替身，不代表生产隔离强度" / c 什么都不动，只在 §16 与 TODO 记为在册残差。
   **我未动 `evaluation.py` 的过滤逻辑与 golden 判分**（本批只把那句已失效的 `TODO: … 落地后替换此函数` 注释订正成现状）。

## 4. 迁移策略（本排期如何推进，不破坏可回退性）

1. **单分支串行**：全部落在 `chore/tech-debt-agentic-discovery-test-2026-10-15`，一步一提交（共享工作区有并行会话代为提交的风险，动 `docs/` 前先重取 `git log`/`git status`）。
2. **不部署**：任何需 126 的验证一律标「待环境」，**不得写成已验收**；`scheduler_enabled` 等默认关的生效面，接线 ≠ 启用。
3. **每步门禁**：`uv run --with ruff ruff check .` + `uv run python scripts/check_doc_sync.py` + 受影响 session 的 `uv run pytest`（Windows 本机无 `make`）。
4. **红线不破**：禁止删用例 / 收窄断言 / 放宽前置条件凑绿；依赖方向 `application → agent-runtime → agent-core` 单向；审计主体服务端断言、不接受请求体自报。
5. **文档回写**：只改状态列；翻复选框前先声明该文件既有计数口径，按**相对口径**记 ± 并留可核命令。

## 5. 验收标准（本排期何时算「做完」）

- §2 各行按其「验收判据」列逐条有**实跑证据**（提交号 + 测试通过数），而非状态行自称完成。
- `ruff check .` 全绿、`check_doc_sync.py` 0 警告、受影响 pytest session 全绿。
- roadmap 阶段 1 每行要么达标并附证据，要么明确标注「待环境 / 待拍板」；**不出现「已上线 / 已支持几十个业务系统接入」这类未达声明**。
- §3 的 5 项拍板结果写入对应 plan；未拍板者保持开项，不强行闭合。

## 7. 阶段 2 提前开工方案（roadmap #12，排期 10/17–10/19，截止 10/19）

阶段 1「我可独立执行」的行已在 10/16 全部做完（提前于 10/30），为不让 10/17–10/30 空转，
把阶段 2 中**本地可完成、不依赖 126/密钥/真库**的行前移。先做 #12（2 人/日，横切关注点）。

**目标**：`/health` 之外第二个横切面——观测装配——满足 AGENTS.md「三层齐备」：单一实现 +
全局装配 + **强制门禁**。判据用 roadmap 原文：**「漏装即 CI 失败」**＋「6/6 覆盖」。

**实测现状（2026-10-16 逐个核，不推定）**：
- 单一实现与全局装配**已存在**：`agent_core.guardrails.app_factory.build_api_app(enable_tracing=…)`
  装配 kernel `TracingMiddleware`，**默认 False**（正是 #12 要的「统一装配、默认关闭」）；6 个 app 全部经该工厂。
- 缺的是**门禁**：`lint_architecture.py` 的 L-3 只做**禁止**（`_INIT_WHITELIST`＝init 不得出现在装配点之外），
  **没有任何规则要求每个 app 都有 init** ⇒ 「漏装」在 CI 里不可见。这正是判据未达成的那半。
- 覆盖缺口实测：`init_tracing` 调用点 agent_server 1 / agent_federation 2 / knowledge-service 9 / exhibition 1；
  **kefu-service 0、nl2sql-service 0**（两应用的 OTEL 配置面也为 0，非"接了没开"）。⇒ 覆盖率 **4/6**。

**影响面**：
- `applications/kefu-service/`、`applications/nl2sql-service/`：各加默认关的观测装配 + 各自 config 面（两应用现无 `otel_*` 字段，需新增，参照 exhibition `config.py` 的 `otel_enabled/otel_endpoint/otel_service_name` 三件套，保持"endpoint 空 ⇒ no-op 降级"语义）。
- `scripts/lint_architecture.py`：新增一条**存在性**规则（与 L-3 的禁止性互补）——每个 app 的健康/装配面必须出现观测装配点，或在显式豁免表里写明理由。
- `deploy/k8s/` 清单：kefu/nl2sql 若此前无 OTEL env，默认关 ⇒ **不需要改部署**（零破坏）；如要开启是后续决策。

**迁移策略（顺序不可反，反了会得到一条永绿门禁）**：
1. 先给 kefu + nl2sql 装默认关的观测装配（行为零变化：不配 endpoint 即 no-op）。
2. 再加门禁断言 6/6 —— **顺序保证门禁落地当天即绿**，且此后任何新增 app 漏装立刻红。
3. 门禁自检须防"永绿"：规则自身要断言"扫到的 app 数 ≥ 6"，否则 glob 失效会让它静默通过（本轮写 `/health` 一致性测试时实踩过同类问题，已用 `scanned >= 2` 自检兜住）。
4. 不改 `build_api_app` 的默认值（保持 False）：默认开属"渐进推广"决策，与 §3 第 4 项 agentic bridge 同类，**不擅动**。

**验收标准**：
- `lint_architecture.py` 新规则在 HEAD 上**先红后绿**（实施前跑一次证明它能抓漏装，实施后跑绿）；
- 6/6 app 有装配点或显式豁免理由；
- kefu/nl2sql 各自 session 不回归、`ruff check .` 绿、`check_doc_sync.py` 0 警告；
- roadmap #12 行按「分项进度」写明"哪半已做、哪半仍开"，不整体翻勾。

**排期**：10/17 装配两应用 + 10/18 门禁 + 反证 → 10/19 收口回写 roadmap。
其后阶段 2 本地可行项：#11（隔离门卫 2/6→6/6，6 人/日，需先审计各服务身份链，量大另出方案）、
#16 脚本加固（小，本地可验：未注入变量即拒跑）、#13/#14/#17 的判据含"前后对比数据/基线读数"⇒ 依赖真库或 LLM 密钥，**待环境**。

### 7.1 #12 实施结果（2026-10-16，提前于 10/19 完成）

- **装配**：kefu-service（模块级装配点，早于 `build_kefu_graph`）、nl2sql-service（`create_app()` 内、
  早于 lifespan 构造模型/连接）各加 `init_tracing(service_name=...)`。**未新增任何 env 变量**——
  kernel `init_tracing` 自带中性 env 读取（`AGENT_CORE_TRACE_ENABLED` 默认 False、
  `OTEL_EXPORTER_OTLP_ENDPOINT` 空 ⇒ no-op），自建配置面只会多一处漂移源。
- **默认关已被实跑证明，不是推断**：清空两个 env 后 `enabled=False`、`status=DISABLED`、
  tracer 类型 `_NoOpTracer` ⇒ 装配零行为变化。kefu **43 passed**、nl2sql **18 passed**。
- **门禁 L-5**（存在性，与 L-3 禁止性互补）：`lint_architecture.py::check_observability_assembly_coverage`。
  **两次反证都做了**：① 把 kefu 装配临时注释掉 ⇒ L-5 **exit=1 且点名** `applications/kefu-service: 无 init_tracing 装配点`
  （随即还原，`git diff` 核实只剩本轮装配改动）；② 枚举自检按设计炸过一次——
  我最初以 `applications/*/pyproject.toml` 作"一个 app"的判据，**漏掉 agent_server**
  （它是根 workspace 成员 `packages = ["applications/agent_server"]`，自身无 pyproject.toml），
  自检报"只枚举到 5 个"而非静默按 5 个通过。⇒ 判据改为与 `_PLATFORM_APPS` **逐个名字比对**，
  目录改名/新增服务未登记都会红。这条自检是今天第二次证明"没有自检的门禁等于没有门禁"。
- **覆盖率 4/6 → 6/6**；`L-3/L-5/L-1/L-2/L-4` 全通过、`ruff check .` 全绿。
- **#12 判据中仍不闭合的部分**：判据原文「漏装即 CI 失败」已达成；
  但「统一装配」我按现状实现为**统一工厂 + 存在性门禁**，未把 `init_tracing` 塞进
  `build_api_app`——那会让 agent_server 精心排序的 provider 装配（其源码有「别挪回去」注释）
  与 Langfuse 抢全局单例，属更大的架构决策。是否在工厂内直接 init，转 §3 拍板追加项。

## 6. #7 消费方影响评估结论（2026-10-16，roadmap 要求「先评估消费方影响」）

**实测：平台对外 `/health` 有三套并存约定**（逐个实读，非推断）：

| 约定 | 服务 | 现状 |
|---|---|---|
| 共享 `HealthResponse`，`status` ∈ `healthy/degraded/unhealthy` | agent_server · nl2sql-service | 已入契约 |
| `{"status": "ok"}` | exhibition-agent · kefu-service（另 `opencode` gateway、warehouse mock） | 字面值**不在**枚举内 |
| `{"ok": true}` | knowledge-service（`/health/live` `/health/ready`） | 布尔键；`ready` 依赖不可用返回 **503** = k8s 就绪探针语义 |

**消费方清单（决定能不能统一）**：

1. `applications/agent_federation/agent/health_check.py::_check_one` — **只看 `status_code==200`，完全不解析 body** ⇒ 对本仓路由决策无影响。
2. `deploy/k8s/20-agent-platform.yaml:160/169/176` — liveness/readiness 走 `path: /health`，k8s 判据是 HTTP 码，不解析 body。
3. **`deploy/k8s/scripts/verify.sh` 与 `portforward.sh` — 会解析字段**：要求 `/health` 含 `otel_status ∈ {ACTIVE,DEGRADED,DISABLED,UNINITIALIZED}`，缺失即判失败/告警。二者指向 **agent_server**（svc/agent-platform:18000→8000），该服务已在共享契约上 ⇒ **不得反向改 agent_server 的 status 语义**。
4. knowledge-service 的 `/health/ready` 503 行为是探针契约的一部分，改成 `status:"healthy"` 会同时动 body 与语义。

**结论与处置**：
- 「统一三套」= 改 **3 个服务的线上响应值**，且 knowledge-service 一侧牵动就绪探针语义。按 AGENTS.md「边界」条（影响下游消费者的对外契约变更须先审计、另行决策），**不在本轮擅动**⇒ 转 §3 待拍板第 6 项。
- 本轮交付**不破坏下游**的那半：新增 `tests/test_health_contract_consistency.py`（8 条）——钉住① 已入共享契约的服务不得退回裸 dict，② 遗留约定逐项登记且**登记失实也报红**（防台账腐坏），③ **禁止冒出第 4 套 `status` 字面值**。提取用 AST 只取 `/health` 路由自身的返回，避免同文件里 `{"status":"uploaded"}`（上传响应）/`{"status":"scheduled"}`（mock 场景数据）造成假阳性——该假阳性本轮已被实跑抓到并修正。
- 附带查得：**当时**本仓 `.py` 有 10 个带 UTF-8 BOM（`ast.parse` 在 `utf-8` 下抛 `SyntaxError` ⇒ 测试统一用 `utf-8-sig` 读，避免以"环境噪声"失败）。
  该数已于同日 §14 清零（`.py` 面 BOM = 0），**读取约定保留**，因为它是"扫描任意未来源文件"的正确约定而非迁就现状。
- 判据「跨服务一致性测试」已具备；「打分测试不破坏下游」= 未动任何对外 body，`eval/run_eval.py` 门禁不受影响。

## 8. 阶段 2 再前移：roadmap #16 强杀脚本 fail-closed（2026-10-16，截止=当日）

**为什么前移**：#16 判据两半，其中「未注入变量时脚本拒跑而非默连本机」是纯本地可验的，不等环境；留在原窗口只会让 10/17–10/30 空转。

**动手前先核事实**：`production-delivery-anchor-map-2026-10-09.md` 已把这条钉到 `scripts/ha_real_kill_verify.py`，并订正过口径——「已可环境变量覆盖，本机 localhost:5433 **仅为默认值** ⇒ "硬依赖本机库"说法不准，真实问题是未注入时会静默默连本机」。本批按后半个判断动手。

**危险定级**：原默认值不只是一个地址，而是**带凭证的完整 DSN**（`postgresql://agent:agent_platform_dev@localhost:5433/…`）。脚本输出是 effectively-once 的取证结论，静默回落等于「真库通过」这句话对应的库不可知。

**改动（全在脚本内，3 处）**：

| 改点 | 内容 |
|---|---|
| 默认值 | 删除。改为 `_require_pg_url()`：缺失或 strip 后为空 ⇒ 打印点名变量的文案 + **退出码 4=配置缺失**，与「断言失败=1」「A 未按时自杀=2」「B 未按时接管=3」分开，包装脚本可据此区分「没配」与「跑崩」 |
| 传参 | `PG_URL` 从模块级常量改为显式形参，穿过 `_proc_a` / `_proc_b` / `_assert_effectively_once` ⇒ 子进程 spawn 时不再依赖 import 期读 env |
| 取证可追溯 | stdout 打印 `target PG: host=… port=… db=…`（由 `_pg_url_label()` 生成）⇒ **DSN 里的凭证不进日志** |

**门禁**：`tests/test_ha_kill_script_gate.py` 5 条，三层各防一种假绿——① 子进程真跑（非零退出 + 文案点名变量 + 输出无任何连接尝试痕迹）；② 纯函数反证（注入即原样返回，证明"拒跑"keyed 在该变量上、而非脚本恒失败）；③ 源码级 AST（该变量读取不得带**非空**默认值——空串默认正是"缺失即拒跑"的写法，故放行；`init_pool` 只接受 `pg_url`；并自述「脚本若不再读该变量则本条失义，请修订判据而非删用例」）。

**非空转反证（5 处变异逐个应红 + 1 处探针自失，均从备份还原并校验 md5 一致）**：

| 变异 | 应变红的用例 | 实测 |
|---|---|---|
| 回落非空默认 DSN | 源码级 AST | 🔴 红（符合预期） |
| `init_pool` 改用字面量 | 源码级 AST | 🔴 红 |
| 退出码改 0 | 退出码断言 | 🔴 红 |
| 拒绝前先打连接痕迹 | token 反证 | 🔴 红 |
| 文案去掉变量名（**两处都去**） | 变量点名断言 | 🔴 红 |
| 文案只去掉一处变量名 | 变量点名断言 | 🟢 绿 ⇒ **探针无效，不是测试弱**：文案本有两处点名，首版变异只替换了一处。订正探针后重跑为红 |

**实跑**：`env -u AGENT_PLATFORM_PG_URL uv run python scripts/ha_real_kill_verify.py` ⇒ `rc=4` + 点名变量、无 traceback（连接前即退出）。CI 不受影响：`ha.yml:56` 已在 job env 显式注入，`ha.yml:70` 是唯一 `run:` 站点（其余对该文件的引用均为 `paths` 触发过滤）。

**本行未闭合**：判据另一半「补双机接管+防覆盖+过载保护场景 / 新场景在真库通过」需真实 PG + 双实例 ⇒ **待环境，不承诺日期**。

**同类风险登记（不擅自扩大范围）**：`deploy/observability/langfuse_proof.py:60`、`deploy/k8s/scripts/e2e_traceparent.sh:21` 同样内置 `127.0.0.1:18000` 默认值，但那是「在运维本机起 port-forward 再取证」的既定用法（`docs/operations/env-126-inventory.md` 有依赖默认值的在册命令），且 langfuse_proof 的只读复核模式根本不打 TARGET ⇒ 是否同样 fail-closed 转 §3 第 8 项待拍板。


## 9. 阶段 2 再前移：roadmap #11 身份门卫装配覆盖（2026-10-16，截止 10-17）

技术方案与逐条验收记录在 `plan-identity-gate-6of6-2026-10-16.md`（§3 设计、§5 本批不做、§8 实施记录），
此处只记排期侧要点：

- **动手前先把「2/6」的定义钉住**：实读结果是**按共享实现算 2/6**（agent_server、agent_federation），
  按"有没有门卫"算是 4/6（knowledge-service、exhibition-agent 各跑自带实现）。⇒ 门禁不能只数存在性，
  否则「6/6 覆盖」会被悄悄换成"都装了个东西"。落法：P13 的 `_IDENTITY_ASSEMBLY` **逐服务登记归属**，
  现有 4 shared + 2 fork，换实现必须有意改表才不报红。
- **一处判据缺陷是被变异反证抓到的**：P13 正则初版匹配裸名字 ⇒「注释掉调用、留着 import」照样全绿。
  改调用形后由专门用例钉住该形状（`test_import_without_call_counts_as_missing`）。
- **装配是 observe 档，但"零变化"要说得准确**：无凭据/不透明 Bearer/skip 面逐字不变（有断言），
  而 JWT 形凭据从"被忽略"变成"验不了就 401"——这是身份门卫的定义本身，已写进方案 §1.2 与 roadmap 行。
- **依赖面**：kefu、nl2sql 此前不依赖 agent-runtime ⇒ 两家 pyproject 新增 `agent-runtime[identity]`
  （已 `uv lock`，301 packages resolved）。不选"挪进 agent-core"：core 无身份层是既有决策，
  造第四套实现更背离"单一实现"。
- **本行仍开的部分**：§3 第 9 项（两套 fork 收敛）、第 10 项（自报租户换服务端断言，含 nl2sql
  租户语义的定义）、以及「enforce 生效 + 灰度记录」的**现网取证**（待环境）。

## 10. roadmap #21 判据交付：架构审计 6 项有效遗留的逐项书面结论（2026-10-16）

> 判据原文是「**每项有书面结论**」，不是「每项都修完」。下表状态取**本轮实读的代码证据**，
> 三条关键结论我另做了源码复核（不整段采信子代理读数）。审计出处 `arch-audit-2026-09-24.md` L19。

| # | 审计原说法 | 现状态 | 依据（file:line，本轮实读） | 剩余缺口 | 有无防回归门禁 |
|---|---|---|---|---|---|
| P2-1 | skill_router 是死代码 | **已修（不再是死代码），覆盖面局部** | 生产调用点 `exhibition_agent/graph/nodes.py:95-103`（`run_skill` 执行前门禁）+ 拒绝分支 `:104-129`；自述已改 `STATUS: WIRED`（`foundation/skill_router.py:5-10`）；测试 3 处（`tests/test_skill_router_wiring.py:22`、`test_skill_routed_endpoint.py:17`、`test_skill_venue_schedule.py:11`） | 门禁表只含 `venue.schedule.query`（`nodes.py:42-44`），`data_analysis.query` 不在内（它走 HTTP 调 nl2sql，不直连 Warehouse）；`route()` 返回值只做判定、**不驱动实际请求形状** | ❌ 无。`lint_architecture.py` 17 个 `check_*` 与 `tests/governance/` 均无「未接线/死代码」类规则 ⇒ 接线被删不会报红（与 #5 判据同源风险） |
| P2-2 | singleflight 竞态未结构性消除 | **原结论已不成立（实现 + 测试都在）** | `packages/agent-runtime/agent_runtime/singleflight.py:19-33`：`_refs` 引用计数 + `_cleanup` 双守卫（`:27-28` refs>0 不删、`:29-30` lock 身份不符不删），`:68-72` finally 递减；回归用例 5 条（`tests/test_singleflight.py:72/92/112/126/151`，本轮新增后两条） | 无（反向守卫「空闲必须真回收」本轮补齐；路径漂移已在审计原文订正） | ✅ 用例即门禁（9 passed，变异反证已验） |
| P2-3 | WS 路径未接中间件/限流 | **部分：错误帧已补，护栏与背压仍未接** | 唯一 WS 路由 `agent_federation/api/server.py:337`（审计的 349/362-364 已漂移），异常分支 `:392-403` 现在**既记日志又向客户端发 error 帧**再断连；`:372` 非法 JSON 也发 error 帧 | 入口护栏**显式豁免 WS**：`server.py:158` `exempt_paths=("/health", "/ws/")`，且 `SecurityGuardsMiddleware` 对非 http scope 直接透传（`agent_core/guardrails/web.py:98`）⇒ 无 admission/coordinator；`:382-388` 逐条 `send_json` **无队列/水位/丢弃策略** = 无背压 | ❌ 无。`tests/unit/test_ws_stream.py` 只覆盖正常流，无 error 帧/限流用例 |
| P2-5 | `.env.example` 与代码不同步 | **部分：exhibition 已补齐（本批 `af2f980`），其余仍有实测缺口** | 已按 `env_prefix` 折算逐应用比对（exhibition `config.py:11` 前缀 ⇒ 10 个 `EXHIBITION_AGENT_*` 均在 `:16-47` 有字段，非孤儿）；审计原句「exhibition 未声明 `NL2SQL_SERVICE_URL`」已不成立（键已在文档中，读点 `skills/data_analysis/skill.py:33`） | ① **agent_server 的 env 键在模板里大面积缺失**（**2026-10-16 重新测量并订正**：原先写"没有自己的 `.env.example`、根文件缺其 11 个无前缀字段"两处都不准 ——
   (a) 数以代码为准：`Settings.model_fields` 共 **87** 个字段，根模板原有 active 键 58 个，**缺 43 个**（不是 11；我此前只读了 `config.py:20-70`）；
   (b) 位置判错：agent_server 的 `.env` 解析基准是**进程 CWD**（AGENTS.md 从仓库根 `uvicorn agent_server.main:app`；根 `Dockerfile:3` `WORKDIR /srv/agent-platform`），
   ⇒ 给它单独建一份**永远不会被读**。已按 §11 把 43 键补进根模板 + 钉桩 `tests/governance/test_agent_server_env_template.py`）；② 代码读而文档缺（**2026-10-16 按同法重测**，口径：对每个应用 `git ls-files` 的 `.py` 扫
   `os.getenv("X")` / `os.environ["X"]` 取键名，与该应用自己那份 `.env.example` 的 active 键做差集）：
   KS **13** 项（原写"等 8 项"是低估；含 `MINIO_PUBLIC_READ`（`clients/minio_utils.py:31`）、`KNOWLEDGE_DEFAULT_TENANT_ID`、
   `CHUNKS_COLLECTION`、`IMG_SUMMARY_ENABLED`、`RAG_EVAL_MODEL`、两个 `ITEM_CONFIRM_*` 阈值等）、
   federation **47** 项（原写"约 50"，接近）、exhibition **1** 项（`F01_SIGNING_SECRET`，`foundation/execution_context.py:70`）。
   **本口径的两个盲区必须随数声明**：⑴ kefu / nl2sql 计数为 **0 不代表已齐全** —— 它们不在自己目录里读 env，
   键由共享层读（`nl2sql_service/conf/settings.py` 等引 `BaseLLMSettings` / `agent_core.llm`），逐应用差集法看不见共享面；
   ⑵ exhibition `config.py` 有 `env_prefix`，前缀拼出来的键名字面扫不到（此前 §5 反向陷阱同源）⇒ 1 项是**下限**。
   因此这 61 项（13+47+1）**只能当"至少要补这么多"用，不能当精确台账**；③ **文档有而代码无**：KS `.env.example` 的观测两键 `KNOWLEDGE_SERVICE_NAME` / `KNOWLEDGE_TRACE_ENABLED`（全包零命中 ⇒ **已定性为"文档化但无人读取的开关"**，不是杜撰噪音：`37d93427`（2026-09-23）把 `ZHANGUI_*` 纯文本替换成 `KNOWLEDGE_*`，而读取方早在 2026-08-21 就移到内核中性键，故新键名**自诞生起无人读**；共 14 处出现/8 个文件，含 dated 记录正文与单测 `delenv` ⇒ 照文档设值 = "以为开了、其实没开"。**本批已修**：14 处改用 `AGENT_CORE_*` + 正向对照用例 + 钉桩 `test_env_example_observability_keys_are_read_by_code`（变异验证：注入 `KNOWLEDGE_TRACE_ENABLED` 或把键名改掉一个字符均转红）；取证链见 `plan-tech-debt-env-var-rename.md` 表注①） | ❌ 无。`check_doc_sync.py` 只核路径与会话数，不核 `.env.example` ⇒ 这类漂移没有自动兜底 |
| P2-6 | 文档口径矛盾 | **大部分已对齐，本轮又清掉两处** | lint 条数已四处同步（`ARCHITECTURE.md` §4.1 / capability-map:326 / 讲解稿 / 锚点表）= 表 17 行·编号 16·函数 17，实数逐行核对；治理 28、HA 19 与实测一致 | 仍开的两处：**(b) 真相源冲突未解**——`AGENTS.md:5` 把 `plan-enterprise-platform-skeleton-2026-09-23.md` 列首位，而 `docs/README.md:60` 已明文标它「已被取代」并记录该冲突 ⇒ 属你拍板项，我不擅动；**(c) session 数口径靠注释维持**——Makefile `test:` 实为 10 行 pytest，但 `check_doc_sync.py:316` 只匹配 `uv run pytest ` 前缀 ⇒ 计到 9，`AGENTS.md:29/30` 用「9 session + 1 个 --extra otel session」这句话把两边对上（结论正确，但一致性靠人读注释） | 部分：条数一致性**无自动检查**（`check_doc_sync` 核不出数字漂移）；session 数有 `check_doc_sync` 半覆盖 |
| P2-7 | MinIO 外部存储失败仅记 warning | **部分：请求路径已 fail-fast，初始化仍 fail-soft** | 上传路径 `knowledge_service/api/import_router.py:229-232` 客户端为 None ⇒ `HTTPException(500)`，`:236-257` 重试 2 次、末次 `logger.error(exc_info=True)` 后**拒绝本次导入**（`:224` 注释自标 P2-7） | `clients/minio_utils.py:12-51` 模块级 `except Exception` ⇒ 记 error 后 `minio_client = None`，不抛、不阻断启动，**且无 env 开关**；`core/config.py:174-187` 的 `validate_credentials()` 列了 `MINIO_ACCESS_KEY/SECRET_KEY` 但**全仓零调用方**（grep 仅命中定义）⇒ 它不构成启动 fail-fast，这本身是第二条待收的孤儿代码 | 部分：fail-open 的现状由「未配密钥 ⇒ 500」间接可测，但没有专门用例钉「初始化失败不得静默」；126 侧的启动 fail-fast 修复已入库（见 `docs/operations/env-126-inventory.md`），线上镜像是否已重建仍是待执行项 |

**本轮据上表顺手清掉的两处不实陈述**（都属于「账面说不、代码说已做」）：
1. `AGENTS.md:5` 的「未接线半成品（P1-7 标注）：human_task / execution_recovery / state_migration /
   payload_externalization / skill_router(exhibition)」——**五项现已全部接线**，
   按 roadmap #5 判据「全仓未接线标注归零」撤除该句（改为「接线 ≠ 默认启用」的准确表述 + 指向本节）。
   同一条还订正了 `docs/architecture/agent-harness-capability-map.md:200` —— 那份仍写 `STATUS: NOT WIRED`
   且称 `route()` 零调用，与 `skill_router.py:5-10`、`nodes.py:95-103` 直接矛盾（同一漂移的第二处落点）。
2. `docs/project-introduction-2026-10-12.md:496` 的「14 条自动检查」→ 16 条（我上一轮只改了三处，
   这条是本轮 grep 复查时补的，属同一漂移面）。

**仍未闭合、且需要你先定的**：P2-6 的 (b) 真相源归属；P2-3 的 WS 是否要接 admission/背压（改的是
对外行为）；P2-5 的 `.env.example` 剩余补齐范围（agent_server 那 43 项已于 §11 补进根模板；**剩 61 项**：KS 13 / federation 47 / exhibition 1，是否值得做双向门禁）；
P2-7 的初始化 fail-fast 是否翻成默认拒绝启动（会让缺配置的部署从「能起但功能坏」变成「起不来」）。

## 11. 阶段 2 再前移：roadmap #21 / P2-5 —— agent_server 的 env 键补进根模板（2026-10-16，截止 10-17）

**目标**：把 agent_server 代码已读、但模板没有的环境变量补进**它实际加载的那份** `.env.example`，
让"照模板填值"对 supervisor 平台成立。本批属 roadmap #21 改法「能接的接」，不改任何对外契约、不动运行时代码。

**计数更正（先认账）**：§10 P2-5 与 §3 第 12 项原先写"11 个无前缀字段""约 60 个键"，前者是**低估**——
我当时只读了 `applications/agent_server/config.py:20-70`。改用代码为准的测量：
`Settings.model_fields` 共 **87** 个字段（含 `BaseLLMSettings` 继承 12 个），
根 `.env.example` 现有 active 键 **58** 个，逐名比对后**缺失 43 个**（口径：键名大写精确匹配 `=` 左侧、
只算非注释行；`git grep -w` 在全部 6 份 `.env.example` 中对这 43 个键**零命中**）。

**影响面（= 零行为变更）**：只新增根 `.env.example` 的注释与默认值行 + 一条一致性用例。
键名依据：`config.py` 与 `shared_schemas/settings.py` **均无 `env_prefix`、无 alias**
（`Settings.model_config = SettingsConfigDict(env_file=".env", extra="ignore", ...)`），
⇒ 环境变量名严格等于字段名大写。默认值一律按代码 Field 默认逐字抄（含 `RUNTIME_MODE=local`、
`SCHEDULER_*` 等 opt-in 关的项），注释复用 `config.py` 自己的话，不自造语义。

**为什么补在根模板而不是给 agent_server 建一份**（这是本轮新核到的事实，也是 §10 ① 那条"整份缺失"
该怎么修的判据）：agent_server 的 `.env` 解析基准是**进程 CWD**——
① AGENTS.md 的运行方式 `uvicorn agent_server.main:app`（从仓库根启动）；
② 根 `Dockerfile:3` `WORKDIR /srv/agent-platform`（镜像内也是根）。
⇒ 两条启动路径都让 `env_file=".env"` 指向**根** `.env`，所以"给 agent_server 建一份它从不读的
`.env.example`"只会制造第二份会漂移的文档。其余 5 个应用各有自己那份，是因为它们从各自目录启动
（`applications/knowledge-service/docker-compose.yml:47` 用 `env_file:` 显式注入）。
**所以本项的"补齐"= 补根模板**；若日后要求 agent_server 能独立部署目录启动，那属另一件事。

**不做（划界，避免越权）**：
1. **不建"env 键必须双向对得上"的全仓门禁**——那是 §3 第 12 项待你拍板的方向（选项 a/b/c）。
   本批只加一条**单向**一致性用例（字段 → 模板必须齐全），因为反向那一半要扫全仓 `os.getenv`
   才能判"文档有而代码无"，范围与口径属拍板项。
2. 不动 KS / exhibition / federation 各自那份（其"代码读而文档缺"的实测缺口仍在 §10 P2-5 登记）。
3. 不改任何字段默认值、不加新字段、不碰 `.env`（已被 `.gitignore` 忽略）。

**验收标准**：
- 用例 `tests/governance/test_agent_server_env_template.py`：87 个字段名全部出现在根模板 active 键中；
  变异验证须证明它非空转（漏一个键 ⇒ 红）。
- `uv run python scripts/check_doc_sync.py` 与 `ruff check .`、`lint_architecture.py` 全绿；根套件 + KS 会话通过。
- §10 P2-5 与 §3 第 12 项的计数按上面对码结果订正，不留"11 个"这个错数。

**截止**：2026-10-17（当日交，含用例与订正回写）。

**交付记录（2026-10-16，早于 10-17 截止）**：根 `.env.example` 追加 `# ===== agent_server（supervisor 平台）模板补齐（2026-10-16）=====` 段，
43 键全部按 `Settings.model_fields` 的字段名与大小写规则生成、默认值逐字照代码（`PAYLOAD_EXTERNALIZATION_THRESHOLD_BYTES=1048576`
即代码里的 `1024 * 1024`），注释复用 `config.py` 原话，未自造语义。复核：补齐后"字段 − 模板 active 键"差集 = **0**（87/87 齐全，脚本实测）；
新用例 3 条 passed；变异验证 M1 删 `DB_POOL_MAX_SIZE` 行 / M2 把 `MAX_SKILL_DEPTH` 改成 9 / M3 段内加 `SCHEDULER_FOO=1`
**三次都转红**（分别在齐全、值漂移、段内孤儿键三个断言上），三次后模板已还原（`git diff` 仅我这 87 行新增）。

## 12. 阶段 1 收口对账（原排期 10/28–10/30，**提前到 2026-10-16 执行**）

**判据来源**：roadmap 各行的「怎么算改好」原文。本轮不新建结论，只做一件事：**逐行用命令重取证据**，
并把与代码不符的账面数字当场订正。三列式 = 断言｜证据（可复现）｜结论。

**全量门禁实跑（本机，`be82e48` 之后的工作树）**：10 个 session 全绿，合计 **2912 passed / 16 skipped**
（root 1067/8（29 deselected=`requires_pg`）、shared-schemas 28、agent-runtime 653/1、agent_server 122、
federation 176、kefu 47、exhibition 368、knowledge-service 412/7、nl2sql 21、observability `--extra otel` 18）；
`ruff check .` 通过、`lint_architecture.py` 通过（打印 16 条编号）、`check_doc_sync.py` 0 警告。

| roadmap 行 | 判据原文（关键句） | 本轮实测证据 | 结论 |
|---|---|---|---|
| #1 阶段0 | 每条结论附代码位置与可复现命令 | 本文 §1 各行 + 本节表格均带 file:line 或命令 | ✅ 达 |
| #2 阶段0 | 规范入库并用于后续所有条目 | `docs/operations/testing-playbook.md` 在册，本节计数即按其 §2.1/§2.2（sha + extras 形态双标注）执行 | ✅ 达 |
| #3 阶段0 | 能连通取到一次读数，或给不可解阻的书面结论 | 126 侧读数不可得（关机）；书面结论已在 `docs/operations/env-126-inventory.md` | ✅ 以"书面结论"分支达成 |
| #4 | 保护覆盖 5/5；真库两类拒绝用例；同名实现只剩一处 | `packages/agent-runtime/tests/test_receipt_generation_fencing.py` **23 条 collected 全过**（含"唯一实现 + 必须带 fence"双向钉） | 🟡 代码面 2/3 达；**真库拒绝用例待环境** ⇒ 本行不闭合 |
| #5 | 全仓"未接线"标注数归零；每模块有测试与独立提交 | **按判据定义达成**：4 个模块 docstring 已改述（`execution_recovery.py:17` 等为"此前状态为 NOT WIRED"历史句），护栏 `test_v3_wiring_assembly.py` **18 条**含"已接线模块不得自称未接线"文档护栏；提交 `c49ee2dd`/`4a7c662e`/`6bf15287` | ✅ 达，**但判据措辞需加口径**：字面 `git grep "未接线"` 仍命中 20 个文件（CHANGELOG/plan 留档、`README.md:562` 另一模块、eval spike 自述），"归零"只能按"模块头自述"读，否则任何人重跑该 grep 都会判红 |
| #6 | 切一次开关，返回值随之变化 | `applications/agent_server/tests/test_health_fields.py` 本轮实取 **16 collected 全过**（roadmap 原记 2026-10-14 的 14 条 ⇒ 已增长，那条属 dated 读数不回写） | ✅ 达 |
| #7 | 跨服务一致性测试 + 打分测试均不破坏下游 | `tests/test_health_contract_consistency.py` **8 条**全过；root session 1067 全过（下游解析形状未动，本轮只做"不破坏"的那半） | 🟡 一致性半达；**「统一形状」转 §3 第 6 项待拍板**；"打分测试"半见下行备注 |
| #8 | 该笔报错有书面结论；图谱重测有实测数据 | `docs/TODO.md:133` 有完整书面结论（已收窄到唯一站点 + 8 条守卫用例已入库），**根因定案仍待一次带 traceback 的再现**；图谱重测需 126 | 🔴 **本行两项均未闭合**（待环境/待再现）。另本轮在该行追加：**站点计数 15 → 17 已失效**（`bd4fb0b` 加了 2 条用例），后续不得再用"恰好 15"定位 |
| #9 | 三处数字一致且已入库 | 重取三口径：`ARCHITECTURE.md` §4.1 表 **17 行** / `main()` 打印编号 **16 条** / 脚本内实现函数 **18 个**（`check()` + 17 个 `check_*`） | ✅ 达，**且本轮抓到并改正我自己写错的数**：口径段原写"实现函数 17 个（`check()` + 另有 16 个 `check_*`）"，两数各少 1；已同步订正 roadmap #9 格与 `production-delivery-anchor-map` 现值行（详见下"账面自纠"） |
| #10 | 造一条无标注响应，输出必须显示"待确认" | `applications/exhibition-agent/tests/test_skill_venue_schedule.py` **15 条**全过；exhibition session 368 全过；行为差分实测仅 `None`/未知 level/空串 3 项变 | ✅ 达（遗留：catalog 4 个写接口无 readiness ⇒ 生产档被拒，须业务方标注） |
| #11 #12 #16 #21 | 见各行 | 判据格内已带 2026-10-16 分项进度（存在性/门禁/脚本半/书面结论各半达成） | 🟡 四行均**不整体闭合**，剩余半属待环境或待拍板 |
| #13–#15、#17–#20、#22–#23 | 见各行 | 依赖真库 / LLM 密钥 / 126 / 集群 / 前端方案评审 | ⛔ **待环境或待拍板，不承诺日期**（§3 现列 **18 行**、其中真待拍板 **17 行**（第 1 行经本轮对码作废；第 17 行内含 5 问），**10/20 前**要给方向。第 15 行 = 本表 #5 那格暴露的判据措辞问题，第 16 行 = embedding 旁路（本轮新登记），第 17 行 = §13 三份 ADR 的选型问）；**#24 例外**：它的「各出决策记录」半已于 10/16 交付（§13），剩下的是那 5 问的答案 + 「文档与代码指向一致」的全量盘点 |

**账面自纠（本轮对码才发现的、我自己交付物里的错数）**
1. `ARCHITECTURE.md:133` 口径段"实现函数 17 个" ⇒ 实为 **18 个（`check_*` 17 + `check()`）**；连带订正 roadmap #9 格与 anchor-map 现值行。
   成因：10-16 加 L-5/P13 时我只重取了"行数"和"打印编号数"，函数数按旧值顺手写的 —— **部分重取等于没重取**。
2. §10 P2-5 ① 的"11 个字段"与"agent_server 整份缺失"（已由 §11 订正为 43 个 + 补根模板）。
3. §10 P2-5 ② 的"KS 等 8 项 / federation 约 50 项"改为实测 **13 / 47 / 1**，并随数声明两个扫不到的盲区。
4. 上一轮我曾把"KS `test_tracing.py` 断言被跨用例 init 污染"写进计划 —— **实读后撤回**：该文件早有 autouse
   `_reset_tracing` fixture（`test_tracing.py:46-52`）前后各重置一次，污染假设不成立；真实缺陷只是 delenv 删了无读取方的键。
5. **台账错项（不是数字）**：§3 第 1 项把 `plan-audit-operator-principal` 登记成"待拍板、零代码"，
   而它**早已实施并合入**（`session_router.py:71` = `server_tenant_id(...)`、P12 门禁在位、
   `116d51b1` → PR #61 → merge `bb2b9a81`）。成因：我照该 plan 的状态行登记，没读 `docs/TODO.md` 里同项的三段已完成追记。
   ⇒ 已作废该行（编号保留，避免打断"§3 第 9/12 项"这类交叉引用），并把 plan 状态行按证据订正。
   真未闭合的那条是**部署侧存量取证**，属待环境。
6. **台账漏项**：`plan-intent-embedder-bypasses-provider-2026-10-10.md` 通篇写"全部等拍板"，却从未进 §3。
   本轮为了"还有哪些未完成计划"而**全量扫 plan 状态行**才发现 ⇒ 补为 §3 第 16 行（现真待拍板 15 项）。
   它的现场证据比我此前任何一条都硬：`EMBEDDING_MODE=mock` 下 `POST /query` **260s 零字节**、
   日志显示仍去 `huggingface.co` 取权重（r12），设 `HF_HUB_OFFLINE=1` 后同一请求 12.8s 完成（r13）。
   ⇒ 教训：**判"台账是否完整"要按全集扫（plan 状态行 + TODO 追记），不能只按我记住的那几条**。

**判据措辞欠账（要不要改判据本身，等你定）**：#5 的"标注数归零"需加"按模块头自述"口径，否则该判据无法机械复核。

## 13. 阶段 3 再前移：roadmap #24 三项悬置选型的决策记录（2026-10-16，截止=当日）

**为什么能前移**：#24 的改法是「各出决策记录（含否决理由与重启条件）」——**写记录不需要我先拿到答案**，
而三项选型今天已各自攒够可核对的证据（现场实测 + 逐个实读定位）。这与 §7/§8/§9 同一策略：把阶段里
「不依赖 126 / 密钥 / 真库 / 拍板」的那部分先做完，剩下的只留一行问。

**交付**：`docs/adr/0008-auth-mode-selection.md`、`docs/adr/0009-vector-store-selection.md`、`docs/adr/0010-ui-stack-selection.md`。
每篇的形状一致：**已决边界（防止把旧问题再问一遍）→ 未决项 → 选项代价 → 否决理由 → 重启条件 → 待回答的那一行**。

**三处把话说正了（都因本轮实测，不是改写口径）**
1. `ADR-0007` 的租户身份选型是 **Accepted 且已实施**（`identity.py:160-232` RS256 `mint_token`/`verify_token`、`:318` 拒启文案）
   ⇒ ADR-0008 不再讨论"要不要 JWT"，只留入口静态 key（`auth.py:23-29`，`:25-26` 未配 key 即不校验的旁路）、
   key→主体映射、`ExecutionContext` 迁 JWT 三问。
2. 「两套向量存储是疏漏」这一判断被证据否掉：KS 要**引擎侧稀疏向量**（`milvus_utils.py:139-157` dense+sparse 双路），
   agent_server 要**向量列与业务表同库**（`rag/store.py:1` pgvector + 自实现 BM25 + RRF）⇒ 两个统一方向各有硬缺口，
   且 `ADR-0003` 当年定的是**驱动**（asyncpg/psycopg）不是存储引擎，不能拿它当"已决"。
3. 「无用户界面」不准确：只读控制台已在仓内（`api/console_router.py` 39 行 + `static/console.html` 343 行 + 用例在册），
   而**全仓零 JS 工具链入库**（`git ls-files` 对 `package.json`/`vite`/`tsconfig`/`*.jsx`/`*.tsx`/`*.vue` 零命中）
   ⇒ 真问题是"要不要为界面引入前端工程 + 构建 + CI 段 + 部署面"，这正是 #18 判据「不新增后端专用接口」要一起看的。

**未闭合的另半（不得声称 #24 完成）**：「文档与代码指向一致」我只做了局部订正（ARCHITECTURE §4.1 计数、
verification-checklist ⑦ 左列、env-var-rename 表注①、audit-operator 状态行），**全量旧文档盘点未做**。

**待你回答（5 问，一行一个字母即可，10/20 前）**：ADR-0008 的 U1 / U2 / U3，ADR-0009 的 A/B/C，ADR-0010 的 A/B/C（选 B 附一句框架与维护人）。

### 13.1 顺手实测出一条门禁覆盖面事实（对本仓文档纪律有影响）

为验证"三篇 ADR 的路径会被存在性门禁兜住"，我在 `docs/README.md` 的索引行里临时插了一条不存在的路径
`docs/adr/9999-does-not-exist.md` 再跑 `check_doc_sync.py` —— **结果仍是「✅ 0 警告」**。
成因（读 `scripts/check_doc_sync.py:41`）：判定面只有根三篇

```python
DOC_FILE_REF_DOCS = ("AGENTS.md", "ARCHITECTURE.md", "README.md")
```

⇒ **`docs/README.md`（我这几轮一直在维护的分层索引）不在这条门禁的覆盖面内**：它写错路径不会有任何东西报红。
本轮因此改为**人工逐条核**这三条新路径确实在版本控制清单里（`git ls-files docs/adr` 命中 0008/0009/0010）。
这不是"要不要修"的新决策，而是既有第 14 行（数字漂移要不要自动兜底）的**同族证据**：`check_doc_sync` 的覆盖面
比直觉窄，只兜根三篇。要不要把 `docs/README.md` 也纳入，随第 14 行一并定。

## 14. E 组技术债清零：`.py` 的 UTF-8 BOM（`docs/TODO.md` §0.4/§5，2026-10-16，截止=当日）

**为什么这算"完成未完成的计划"**：TODO §5 那条开了 13 天，**处方已写在条目里**（"若要清零：改文件 + `git diff` 验证只丢 BOM、
无其他字节变化"）⇒ 属"已敲定方案、有文档记录"的存量项，不是需要新拍板的方向。E 组其余 4 条（D1/D4/D5/D7）各有"为什么留着"的理由，
本轮只动这一条判据可机械执行的。

**目标**：全仓 `.py` 的 UTF-8 BOM 清零；不改任何行为、不动判定强度。
**影响面**：10 个 `applications/nl2sql-service/nl2sql_service/**/__init__.py`（各删前 3 字节，文件剩 1 字节）
＋ 3 处注释/docstring 的事实订正（`scripts/lint_architecture.py:1021-1025`、
`tests/governance/test_audit_operator_principal.py:308-314`、`tests/test_health_contract_consistency.py:101-103`）。
**迁移策略**：逐文件字节断言 `old == b'\xef\xbb\xbf' + new`；**保留** `utf-8-sig` 读取约定（偏离原处方两条，理由见 §5 闭合记录：
兼容是"扫描未来源文件"的正确约定，摘掉会让 P12 在未来 BOM 文件上产生假阳性；BOM 回归用例自带合成文件 ⇒ 不需调转，调转等于削防线）。
**验收**：`.py` BOM 复扫 = 0；nl2sql session 21 passed；治理+契约合跑 37 passed；`lint_architecture.py` rc=0；`ruff check .` 全绿；
`git diff` 核得 `- [ ]`→`- [x]` 恰 **1** 处、其余复选框零变更。
**边界（不倒扣）**：清零只覆盖 `.py`。当时仓内仍有 **4 个非 `.py`** 带 BOM（`ARCHITECTURE.md`、`docs/README.md`、本篇、
`docs/plans/p0-4-blind-except-inventory.txt`）——Markdown/文本不涉 PEP 263 加载语义，不属本项判据，本轮不顺手改。
**（2026-10-16 §19 批次后现值：3 个）**——本篇自己的 BOM 在那一批的文件重排中被去掉了（**属偏离，见 §19 末段**），现存 `ARCHITECTURE.md`、`docs/README.md`、`p0-4-blind-except-inventory.txt` 三个仍带 BOM（按 HEAD blob 现取，不是做减法）。

## 15. E 组技术债 D4：ruff `ignore` 逐包收窄（2026-10-16，截止=当日）

**为什么这是"完成未完成的计划"而不是配置洁癖**：TODO §5 那条 D4 的判据写得清清楚楚
（"需逐条评估删除后是否仍违规"），而**这条判据可以当场机械执行** ⇒ 属已定方案的存量开项，不需要新拍板。

**方法上的一个必须讲清的点**：本仓有 **6 份 ruff config**（根 + federation + exhibition + knowledge-service + agent-core + agent-runtime），
ruff **按最近 config 分层生效**。所以"只跑一次 `ruff check .` 看根配置"会得出错的数——实测 E402 在根子树 A=25，
而绕开配置的 B=57，差 32 恰好等于 federation 28 + agent-runtime 4。⇒ 两个口径分开报：

| 口径 | 命令形状 | 回答的问题 |
|---|---|---|
| **A（CI 等价）** | 只从该包 config 摘掉这一条 → `ruff check <包目录>` | 摘了会不会让 CI 变红 |
| **B（真实存量）** | `ruff check <包目录> --isolated --line-length 120 --select <R>` | 这族规则若启用会报多少 |

**逐包实取（A / B）**

| config | 规则 | A | B | 处置 |
|---|---|---|---|---|
| 根 | E731 | 0 | 5 | **删**（5 处全在嵌套包，其各自 config 仍豁免） |
| 根 | E402 | 25 | 57 | 保留（真实存量） |
| 根 | B008 / B017 / PERF102 / RUF059 | 0 | 7 / 8 / 4 / 37 | 保留但**登记为死配置**：这四族不在 `select`，对 `ruff check .` 恒 0，唯一作用面是 `make type --select ALL` ⇒ "要不要纳入 select"转 §3 第 18 行 |
| federation | E402 / E731 | 28 / 4 | 同 | 保留（deliberate：`load_dotenv()`/`sys.path` 后再 import） |
| exhibition | B008 / E402 / E731 | 0 / 0 / 0 | 0 / 0 / 0 | **整块删**（3 条） |
| knowledge-service | E722 | 0 | 0 | **删**；原注「存量 1 处 `node_rrf.py:39`」**已不成立**（该行现在不是 bare except） |
| knowledge-service | F403 / F405 / F811 | 6 / 17 / 1 | 同 | 保留；F405 原注 18 ⇒ **按实取订正为 17** |
| agent-core | E722 / F403 / F405 / F811 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | **整块删**（4 条；连被 `extend-exclude` 排掉的 `tests` 也复扫过） |
| agent-runtime | E402 / E731 | 4 / 1 | 同 | 保留 |

**净结果**：21 条豁免 → **删 9、保 12**（`tomllib` 逐 config 复算）。
**非空转反证**：每条删除都放了一次探针——根子树 `f = lambda: x` 报 E731；`agent_core/` 里 bare except / `from json import *` / 重复 `def a()` 分别报 E722 / F403+F405 / F811；
`exhibition_agent/` 里 import 后再 `from os import sep` 报 E402、lambda 报 E731；`knowledge_service/` 里 bare except 报 E722。探针全部删除，`git status` 无残留。
**自我纠正两处**：① 我第一版扫描脚本**没检查 ruff 返回码**且用正则重建 `ignore` 数组，把带行内注释的 KS 配置读坏过，读数一度不可用 ⇒ 改成 `tomllib` 解析 + 只删单个 token + 校 `rc==2`；
② 我第一次的 KS E722 探针写成了 `except Exception`（那是 BLE001 不是 E722），据此差点得出"删了不生效"的错结论 ⇒ 换真 bare except 后报红。
**验收**：`ruff check .` 全仓通过；agent-core + exhibition + knowledge-service 三会话合跑 **1129 passed / 15 skipped**（与收窄前同数 ⇒ 零回归）。

## 16. roadmap §四「七条生产交付判定标准」逐条对码复核（2026-10-16，截止=当日）

**为什么现在做**：§四 是一二期分界线、12/04 交付判定的唯一判据表，而它的判定列写于 2026-10-09（第 3 条 10-14 订正过一次）。
本分支相对 main 的提交数在本节写入过程中从 40 涨到 41（§16 自己就是那个 `0494b1b`）⇒ 这类"随提交递增"的数一律以命令现取，不拿本节当账面值：`git rev-list --count main..HEAD`。这些提交动了其中多条的底层事实 ⇒ 判据表若不同步对码，「阶段 1 收口」就只是把 §2 的行做完、判定口径仍在漂移。
**本节的产物只有对码结论与取证命令，不改 §四 表体**（那张表按 roadmap §八 的既有范式留作当日快照，我在表下加指针行）。

**口径先定义（本节所有计数的读法）**：
- 「生产写入点」= `git grep` 命中且**不在 `tests/` 与 `docs/`** 的引用；字段存在 ≠ 有人填它。
- 「达成」= 判据要求的**覆盖面**有代码 + 有断言；开关默认关、真库未跑、待拍板，都不算达成，只算半边达成并写明另一半卡在哪。
- 全部读数为**本机工作区 = tip `f641ca5`**，非现网 rev；现网读数按 AGENTS.md 观测硬规矩第 3 条必须绑 Pod `GIT_REV` 另取。

| # | 标准（§四原文判定 → **本轮**） | 2026-10-16 对码实取 | 结论 |
|---|---|---|---|
| 1 | 全链路真实执行、无未接线模块：「部分达标：4 处未接线」 | 5 处（4 模块 + exhibition `skill_router`）接线已落（TODO §3 三行已翻勾）；`.py` 内**活跃** `NOT WIRED` 标注 **0**——4 处命中全为「**此前**状态为 NOT WIRED，P1-7 审计披露 2026-09-24」的过去时描述；反漂回有门禁：`applications/agent_server/tests/test_v3_wiring_assembly.py:213`（main.py 必须仍引用这 4 个模块，否则「未接线」立刻复活）+ `:232-243`（已接线模块的 docstring 不得再声称「仍未接线」） | 「无未接线模块」半边**达成**；「全链路真实执行」仍受 `SCHEDULER_ENABLED` 默认 `False` 限制 ⇒ 不得读成「已上线」 |
| 2 | 不丢状态、不重复执行：「部分达标：防覆盖 3/5」 | 代码面 **5/5**（`68a44290`，§12 已登记）；`packages/agent-runtime/tests/test_receipt_generation_fencing.py` 实数 **5** 条断言；执行层双实例故障转移与真库拒绝用例**待环境**（126 关机） | 3/5 → **代码面 5/5**；标准整体仍未达标（缺环境半边），按 §四 规则句只能写「标准环境已验证、多物理机待环境」 |
| 3 | 可重复部署路径 + 真实部件状态监控 + 可执行升级与回退手册：「部分达标，缺聚合监控与升级手册」 | `/health` 25 键 + `test_health_fields.py` **16 passed**（部件状态半边达成）；**手册半边原句不成立**：`docs/operations/minimal-release-runbook.md` §2「唯一上线通道（六步）」+ §7「故障与回滚预案」（7.1 代码回滚 / 7.2 配置回滚 / 7.3 schema·数据）与 `ha-runbook.md`（Incident Checklist / Recovery Decision Tree）**早已在库**；指标面须分两层读：`agent_server` 全仓 grep `metrics` **0 命中**，而 `agent_federation/agent/metrics.py`、`exhibition_agent/observability/metrics.py` 各有一份**自建轻量 registry**（两处 docstring 明写「不引入 prometheus/otel meter 重依赖」）⇒ 「无 Metric Registry」过宽 | **达成 2/3**（部署路径 + 部件状态 + 手册均在位）；真缺口 = **跨请求聚合指标/仪表盘**与错误率·超时率·降级率基线，且手册需绑定现网 rev 复核后才可作对外结论 |
| 4 | 存在可操作的用户入口：「未达标（仅 3 个内部调试页）」 | 入库 `.html` 共 **5** = 应用页 4（`agent_server/static/console.html`、`exhibition_agent/static/index.html`、KS `import_process/page/import.html`、KS `query_process/page/chat.html`）+ 文档页 1（`docs/architecture/overview.html`）⇒ 「3 个」漏数了 KS 两个**面向操作的功能页**；但 KS 属子服务，平台主进程仍只有 1 个调试控制台 | **判定不变（未达标）**，只订正页数与「都是调试页」这句定性；界面选型是 §3 待拍板项（ADR-0010），不代拍 |
| 5 | 任一客户数据在所有路径下不跨客户可见：「部分达标：机制完整，覆盖 2/6」 | 装配覆盖 **6/6** 且有**归属记账**：`scripts/lint_architecture.py:589-621` `_IDENTITY_ASSEMBLY` 逐服务登记「用哪一套实现」，**P13** 门禁按调用形正则校验存在性（`:1170` 打印「6/6 服务均有身份门卫装配点」，漏装/换实现即 CI 红）；构成为 4 个 `shared` + 2 个 `fork:`（KS `TenantHeaderMiddleware` 零依赖 runtime、exhibition `resolve_execution_context` **逐端点**且 DEV 档刻意不验签）⇒ 2/6 → 6/6 装配；强档仍受 `DEPLOY_ENFORCE_IDENTITY` 默认 `False` 与 2 处 fork 待收敛限制 | **两层口径不得混说**：装配覆盖 **6/6 达成**；「所有路径下不跨客户可见」的**强档未验证**（fork 收敛待拍板，见 `docs/plans/plan-identity-gate-6of6-2026-10-16.md` §5 第 1 项与第 3 项；真库双租户外溢待环境） |
| 6 | 每次回答可追溯身份、调用、数据来源、成本：「**达标**」 | 拆四问取数：①**调用** ✅ `planner/execution_graph.py:66-79` 落 `TrajectoryRecord`（plan / steps / planner / tenant_id / snapshot）；②**成本** ✅ 同记录带 `total_tokens` / `total_cost`；③**身份** ⚠️ 落的是**租户**（`tenant_id` per-request），自然人主体当前恒为服务端单一主体 `server_tenant_id(default_tenant_id)`，逐审批人身份待 ADR-0007 强档；④**数据来源** ❌ `ForensicContext.external_inputs` / `external_task_receipts` / `effect_receipts` 三个取证字段**生产零写入点**（双通道复核：全仓 `.py` 命中仅 `forensic.py` 自身定义/序列化/diff + `tests/`；唯一生产构造点 `execution_graph.py:58` 只填 `model` + `planner_version` 两维），外部回执另有落点（`awaitable_task.py:158-159` `submission_receipt` / `completion_receipt` 在任务行上）但**未汇入每次回答的取证记录**；exhibition 的 `citations` 属 skill 返回体（`capabilities.py:371`），不是平台通用取证面 | **本轮唯一被下修的判定：达标 → 部分达标**。依据是「载体在位 ≠ 字段被填」——前三问里两问成立、一问降级为租户级，第四问（数据来源）结构性缺写入点。**教训**：多面标准（"身份+调用+来源+成本"）必须逐面各取一次写入点证据，任一面拿"有这个 dataclass"当达标就会高估整条 |
| 7 | 版本号、变更记录、待办清单、决策记录与代码一致：「部分达标，变更记录与决策记录待 #1 收尾」 | 待办清单半边：§12 已逐行重取并改掉 4 处账面错数；决策记录半边：`docs/adr/` 现 **8 篇**（0003–0007 + 本轮补 0008 认证方式 / 0009 向量存储 / 0010 界面选型，三篇状态均「未决」，只登记已决边界·选项代价·重启条件，**不代用户拍板**）；变更记录半边**当时仍不成立**：`CHANGELOG.md` 最新一节停在 2026-10-09，本分支相对 main 的提交（`git rev-list --count main..HEAD`，写入时点 40→41）未回写；门禁计数已订正（`ARCHITECTURE.md:133-134` 表 17 行 / 打印 16 条 / 实现函数 18 个，含自我纠错句） | 决策记录由「无书面记录」推进到「**有记录、待拍板**」；变更记录半边**同日已闭合**（§17 补了未发布窗口节）。**但本节对不上的一处归因要登记**：§四 第 7 条把变更记录挂在「待 #1 收尾」下，而 #1 自己的判据列只写「每条结论附代码位置与可复现命令；清单与代码不矛盾」⇒ **变更记录在 roadmap 里从来没有对应整改行**，本窗口靠 §2 新增行才有一个有判据有截止日的落点。第三个 facet「版本号」实测三处互不对应（见 §17），亦无整改行 ⇒ 转 §3 第 20 项 |

**汇总（口径：§四 表体的判定列，逐格读）**：部分达标 **5 → 6**（第 6 条下修进来）、未达标 **1**（第 4 条）、达标 **1 → 0**。
⇒ **七条全达标的前置**里，本窗口内还能靠代码/文档推进的是第 1、3、5、7 条的指定残口；第 2 条与第 5 条强档、第 8 类真库/双实例场景**全部待环境**；第 4 条待 UI 选型拍板。

**复跑命令**（本机 `uv run`，全部只读）：
```bash
git grep -n "NOT WIRED" -- '*.py'                                  # 期望：4 处且全为「此前状态」过去时
git grep -n "external_inputs\|external_task_receipts\|effect_receipts" -- '*.py' | grep -v /tests/
                                                                   # 期望：仅 forensic.py 自身（=第 6 条④的证据）
git grep -n "ForensicContext(" -- '*.py' | grep -v /tests/         # 期望：1 处 execution_graph.py:58
git ls-files '*.html'                                              # 期望：5
uv run python scripts/lint_architecture.py                          # 期望：P13 打印 6/6
uv run pytest packages/agent-runtime/tests/test_receipt_generation_fencing.py applications/agent_server/tests/test_health_fields.py -q
```

**本节未取证的边界（登记，不当已完成）**：① 未跑现网任何读数（本窗口不部署，§四 第 3 条手册绑定 rev 的复核因此也没做）；② 第 6 条「成本」只核到轨迹记录字段，`cost_governance` 的预算拒绝行为是否有断言未在本轮取；③ 第 3 条的「错误率/超时率/降级率基线」我只证明了"平台侧无聚合指标面"，没证明"没有任何基线数据"（评测面 `eval/` 与 KS 的 417 条不在本节判据内）。

**同批顺手做的一件事与"没做的那件事"要分开说**：`docs/architecture/agent-harness-capability-map.md` 是**基线 `48c25fe` 的 rev 绑定快照**，其中 5 行 P1-7/未接线判定、`/health` 行的两点残差、取证面两行的 ✅ 档都已过时。
本批**只在该文件自述的「换 rev 先复跑」规则下补了一段换 rev 提示（指针 + 锚点 commit + 指向本节）**，**没有改写任何判定行**——它按自己的纪律就该留作当日快照，改它会毁掉"读数绑定 rev"这条它自己立住的规矩。判据现状以 §16 为准，不以那张表为准。

## 17. 变更记录补齐（§四 第 7 条残口的交付记录，2026-10-16，截止=当日）

**做的事**：`CHANGELOG.md` 在 newest-first 位新增一节「未发布窗口补记：2026-10-10 – 2026-10-16」，覆盖上一节（2026-10-09）之后进入本分支祖先链的全部提交。

**判据口径（不定这句话，"变更记录与代码一致"就无法核对）**：变更记录有三种可能的"一致"——
(i) 逐提交转写；(ii) 按批次聚合 + 给可机械枚举的 rev 范围；(iii) 只写面向使用者的功能变化。
读本文件既有 52 节的结果：全部是 (ii) 形态（一节一主题 + 改动面 + 证据），**没有一节是逐提交转写** ⇒ 本批按 (ii) 补齐，与文件既有范式一致，并在新节开头原样写明"逐提交清单请用 `git log --oneline --since=2026-10-09 HEAD` 现取，本节不复制粘贴 subject"。**不声称达成 (i)**，避免用整体性名词描述现场证据。

**自查（全部当场重取，不引用账面）**：

| 断言 | 命令 | 读数 |
|---|---|---|
| 窗口提交数 | `git rev-list --count --since=2026-10-09 HEAD` | **120**（测量时点 HEAD=`0494b1b`） |
| 本分支独有 | `git rev-list --count main..HEAD` | **41**（main 侧即 79；同一时点） |
| 锚点与描述一致 | 逐个 `git log -1 --pretty=%s <锚>` | 新节 11 个锚点全部命中且 subject 语义与该行描述对应（`c49ee2dd` `4a7c662e` `6bf15287` `68a44290` `18b6954` `d31f247e` `bd4fb0b` `be82e48` `a618e4b` `f641ca5` `0494b1b`） |
| 历史节零改动 | `git diff --numstat CHANGELOG.md` | **16 added / 0 deleted** |
| 文档门禁 | `uv run python scripts/check_doc_sync.py` | ✅ 0 警告 |

**关于"补记之后又产生新提交"的自指问题（不回避）**：窗口节覆盖到 `0494b1b`，而 §17 自身的提交、以及接下来记录复跑的提交，都落在窗口节之后 ⇒ 若把判据读成"每个 commit 都必须有一行"，这条标准永远闭合不了。
本排期采用的读法写在明处：**判据 = 窗口内每个交付批次都有可指回的节**（批次以 roadmap 行号 + 锚点 commit 标识），不是逐提交登记。
下一次补记时以 `git log --oneline 0494b1b..HEAD` 现取增量，不回头改本节。

**同时把第 7 条里我原先归错的一处账纠出来**：§四 第 7 条把「变更记录与决策记录」都写作"待 #1 收尾"，但 roadmap #1 自己的判据列只有「每条结论附代码位置与可复现命令；清单与代码不矛盾」——**变更记录与版本号这两个 facet 在 roadmap 里从来没有对应整改行**（无判据、无人/日、无截止日）。⇒ 本批在 §2 新增变更记录行（判据=可核对的窗口节 + rev 范围，截止 10/17）、在 §3 新增第 20 项（版本号），让它们有落点而不是继续挂在一句交叉引用下。**教训**：拿"某条标准待 X 收尾"当证据前，要回去读 X 的判据列覆不覆盖这句话——我这次就是照 §四 的交叉引用写了 §16，回头对 #1 才发现覆盖面不符。

**版本号 facet 实测（转 §3 第 20 项，本窗口未动）**：根 `pyproject.toml:3` = `0.1.0`，9 处 `version =` 里 7 个 `0.1.0` + federation `2.0.0` + knowledge-service `1.1.0`；tag 侧存在 `v2.0.0` / `v3.0.0`（另 3 个 `archive/*`）；部署面用的是 `GIT_REV` 而非 semver ⇒ **三套版本面无书面映射**，"版本号与代码一致"目前无可核对定义。

**边界（不粉饰）**：未打 tag、未改任何 `version`、未部署、未连现网取任何读数；新节里的通过数一律标"批次当时实跑的 tip"，不合并成单一数字。当前 tip 的全量 10-session 复跑见 §18。

## 18. 本分支 tip 的全量门禁复跑（2026-10-16）

**为什么单列一节**：§12 那次 10-session 全量跑在 `b76108f` 之后的 tip 上，而此后本分支又叠了 D4 收窄、BOM 清零、§16/§17 三批 ⇒ 「全绿」这句话必须绑定**当前树**才有意义（roadmap 执行约束第 1 条）。

**读数**（命令 = Makefile `test` 目标的逐 session 等价，本机无 `make`，逐条 `uv run pytest` 跑；根 session 带 `-m 'not requires_pg'`，观测 session 带 `--extra otel`）：

| # | session | 读数 |
|---|---|---|
| 1 | 根会话（CI 第 1 条 = `uv run pytest -q -m "not requires_pg"`，**无路径参数** ⇒ `testpaths` 同时含 `tests` 与 `packages/agent-core/tests`，不是只 `tests/`） | **1067 passed / 8 skipped / 29 deselected**（607.78s）**（2026-10-16 §24 订正：本行原标"根（tests/）"是错的标签——只跑 `tests` 实取 720 passed，差值 ~347 即 agent-core 会话被折进了第 1 条）** |
| 2 | shared-schemas | 28 passed |
| 3 | agent-runtime | 653 passed / 1 skipped |
| 4 | agent_server | 122 passed |
| 5 | agent_federation | 176 passed |
| 6 | kefu-service | 47 passed |
| 7 | exhibition-agent | 368 passed |
| 8 | knowledge-service | 412 passed / 7 skipped |
| 9 | nl2sql-service | 21 passed |
| 10 | observability（`--extra otel`，真 SDK） | 18 passed |
| — | **合计** | **2912 passed / 16 skipped**，10 个 session 全部退出码 0（脚本末行 `ALL SESSIONS DONE`） |

**rev 归属（这条必须写清，否则读数不可核对）**：本轮跑在 `f641ca5` 的**代码树**上，但 10 个 session 执行期间我正在写 §16/§17（三次未提交的文档编辑）⇒ 严格读数是「`f641ca5` 代码树 + 中途未入库的 docs」。
可核对性靠两点，不靠断言：① 本批改动面只有 `CHANGELOG.md` + 两篇 `docs/plans/*`，**零 `.py`**；② 总数与 §12 那次在干净 tip 上的全量**逐 session 同值**（2912 / 16）⇒ 没有任何用例在数文档内容，中途编辑不构成读数影响。
**消除歧义的处置**：提交后在当前 tip 上另起一轮 clean-tree 复跑，结果就地补在下行；两轮同值才对外用「本分支全量门禁绿」这句。

**第二轮（clean-tree 复跑，2026-10-16 06:41–06:55，工作区 = `7a25583`，代码树与 `f641ca5` 逐字节相同）**：10 个 session 逐条同值 ——
根 **1067 passed / 8 skipped / 29 deselected**、shared-schemas 28、agent-runtime **653 / 1 skipped**、agent_server **122**、agent_federation **176**、kefu **47**、exhibition **368**、knowledge-service **412 / 7 skipped**、nl2sql **21**、observability(--extra otel) **18** ⇒ **合计 2912 passed / 16 skipped，全部退出码 0**（脚本末行 `ALL SESSIONS DONE`）。
**与 §12 那次的关系**：§12 记的也是 2912 / 16，三轮独立读数（`b76108f` 时点、`f641ca5` 代码树 + 中途 docs、`7a25583`）逐 session 同值 ⇒ 本轮之后的那批文档改动**没有改变测试面**（`.py` 自 `f641ca5` 起未再变动）。
**仍未消除的残留（说清楚，别读成"零瑕疵证据"）**：本轮 20 分钟里我提交了两个 doc-only commit（`bd4a900`、`7a25583`），所以它也不是严格意义上的"零写入静态树"；要做到那一点必须 20 分钟内不动任何文件，本窗口做不到。判定这句对外可说的强度是「**`.py` 自 `f641ca5` 起逐字节未变 + 三轮同值**」，不是「一次 pristine checkout」。
**耗时会漂**：root session 607s→140s、agent_server 46s→495s、otel 439s→24s（首轮含 `--extra otel` 依赖解析；并发会话抢 IO）。**耗时不可用作回归判据，只有 passed/skipped 计数与退出码可以**。

**本节的读数绑定关系要补一句（否则下一批会把它读成现值）**：上表两轮都跑在 §19 那份新用例**入库之前**，
所以从 §19 起 exhibition 应为 **371**（+3）、合计应为 **2915 passed / 16 skipped**，而不是表里的 368 / 2912。
本窗口没有再花 20 分钟重跑整轮，**这个 +3 是由"只新增一个测试文件、零产品代码改动"推出的**，不是实测；
对外引用前先重跑一轮确认（单条已实测：`uv run pytest applications/exhibition-agent/tests -q` → 371 passed）。

**仍未覆盖的范围（不把 10 session 说成"全部验证"）**：`make ci` 还含 `ruff check .` + `scripts/lint_architecture.py` + 启发式 eval；前两者本批已单独跑过（§15 验收、§17 自查 `check_doc_sync.py`），eval 未在本窗口重跑。真库/双实例/现网类用例仍属 §2 的「待环境」，不随本节翻状态。

## 19. 阶段 2 再前移：exhibition 的 env 模板门禁（roadmap #21 / P2-5，2026-10-16，截止=当日）

**先记一条我自己犯的取证错（它差点变成一条假缺口）**：我用「字段名大写 ∈ 模板键集合」去比 exhibition，得出**「10 个字段里 9 个没记载」**。
错在**没读 `model_config`**：本服务 `env_prefix="EXHIBITION_AGENT_"`，pydantic-settings 的真实 env 名是 **前缀 + 字段名大写** ⇒ 模板里 10 个键**一个不缺**。
订正后的实取：`exhibition-agent` prefix=`EXHIBITION_AGENT_` fields=10 **missing=0**；`agent_server` prefix=`''` fields(own)=79 **missing=0**。
⇒ 「模板齐不齐」这类判定**必须先折算 env 名**（前缀 / `alias` / `validation_alias` 三种都会让字面比对失真），这是本窗口第 4 次「探针错 ≠ 规则错」。

**既然事实是"已记载"，交付就改成"让它在结构上不能退回去"**（登记为门禁而非账面结论）：新增 `applications/exhibition-agent/tests/test_env_template.py` 3 条用例——
① **正向齐全**：`Settings.model_fields` 每个字段的真实 env 名必须是 `.env.example` 里的 active 键；
② **值 == 代码 `Field(default=...)`**：模板不杜撰、不滞后（bool→`true`/`false`、`None`→空值）；
③ **前缀内反向不悬空**：模板里任何 `EXHIBITION_AGENT_*` 键都必须是字段——本服务 `extra="ignore"`，带前缀而非字段名的键**代码根本不读**，正是 KS 观测两键那种死键形状。
另有一条**守卫本用例自身前提**的断言（前缀被人改掉 ⇒ ①②的键名整体失真，必须显式改口径）。

**非空转反证（四条变异，全部 RED 于正确的理由）**：

| 变异 | 结果 |
|---|---|
| 删掉 `EXHIBITION_AGENT_LOG_LEVEL=` 一行 | `1 failed`（正向齐全） |
| `WAREHOUSE_TIMEOUT` 默认 `10.0`→`9.9` | `1 failed`（值漂移） |
| 追加 `EXHIBITION_AGENT_NOT_A_FIELD=1` | `1 failed`（死键） |
| `config.py` 的 `env_prefix` 改 `"FOO_"` | `2 failed / 1 passed`（前缀守卫 + 正向齐全） |

两次变异都是**先备份字节、改文件、跑 pytest、原字节写回**：`restore byte-identical: True`，`git status` 对这两个文件干净。
**过程中还纠了我自己一次执行方式错误**：第一轮反证用 `python -m pytest` 起子进程，得到 `ModuleNotFoundError: exhibition_agent` 的 **rc=4（用法错误）**，我把这种红当成了"用例被击中"——**它证明的是环境不对，不是规则生效**；换 `uv run pytest` 后才是上面四条真红。

**读数**：exhibition session **368 → 371 passed**（+3，既有用例零删改），`ruff check` 该文件全绿。

**范围结论（把"能做/不能做"这条线划清）**：全仓用 pydantic-settings 的**只有 2 处**（`agent_server`、`exhibition-agent`），两家现在都有同款门禁。
其余 4 家（kefu / nl2sql / federation / knowledge-service）的配置面是 `os.getenv` + dataclass，**从字段名推不出 env 名** ⇒ 它们的模板齐全只能人工枚举，
即此前登记的「约 61 个键」那个口径**是人工清点结果、不是可机械折算的判据**——它继续留在 §3 第 12 项待拍板，本批没有把它假装做成门禁。

**同批被拦下的一项（登记，不绕过）**：roadmap §八 明写"打分 15 题 80% 为历史记录，需建立当前基线后替换"。
`make eval` = `uv run python eval/run_eval.py --fail-below 0.8`，而 `eval/run_eval.py:46-50` 在无 `LLM_API_KEY` 时**只打 WARN 并回退启发式路径，不需要密钥** ⇒ 我按 `make eval` 发起复跑，
但自动执行层以"该评测需要 LLM key"为由拦下。**我没有换姿势绕过它**：这条记为「**待用户放行**」，§八 那句历史记录因此**仍未换成现值**。
需要的话，请放行 `uv run python eval/run_eval.py --fail-below 0.8`（纯启发式、不出网、不读密钥）。

**本批的一处编码偏离（写在发生的地方，不让它读起来像无损）**：§19 末尾那次"把 §19 挪到 §18 之后"的文件重排用 `write_text(new)` 完成，
顺带**去掉了本篇的 UTF-8 BOM**（HEAD 里本篇是带 BOM 的，见 §14 边界句）。事后想按原样补回被权限层拦下（判定为"给 Markdown 注入 BOM"），**我没有换工具绕过**。
保留现值的理由：`.md` 的 BOM 不属任何判据（§14 已写"不涉 PEP 263 加载语义"），且本仓 `.gitattributes` 是 `* text=auto eol=lf` + `*.md text eol=lf`，无 BOM 才是它的目标形态。
后果与核对方式：本篇在 HEAD 里**从此为无 BOM**，`git diff` 的首个 hunk 就是第 1 行的 BOM 变化（不是内容改动）；其余 3 个非 `.py` BOM 文件本批未碰。
教训同 §14 那条同源：**改文件要按字节约定改**——我这次是"顺手用了一次不带 BOM 的写回"，属可避免的偏离。

## 20. TODO §4 的 F01 对码：判据由「未落地」订正为「只差一处、且差的是评测语义」（2026-10-16）

**怎么挑到它的**：§19 之后继续找"本地可完成、不需拍板、不需环境"的开项，扫 `docs/TODO.md` §4（会展业务骨架 6 条）时，F01 那行写的是 `enforce_scope_filter` **落地**——但代码读起来不像没落地。

**实取（三通道，不按字面判）**：

| 事实 | 命令 | 读数 |
|---|---|---|
| 生产实现在位 | `sed -n '150,190p' applications/exhibition-agent/exhibition_agent/foundation/execution_context.py` | `enforce_scope_filter` 是完整实现（租户一致 + `ctx.scopes` 收窄），非桩 |
| 评测是否真在跑它 | `git grep -n enforce_scope_filter` | `evaluation.py:128` 的 `_evaluate_cross_tenant_negative` **在生产代码上判越权**（审计 P1-9 那批改的：先用 mock 过滤再统计 ⇒ 恒 0 的自证式假绿） |
| mock 还剩几处 | `git grep -n _mock_scope_filter` | **3 行 = 1 个 def + 1 处调用（positive 路径）+ 1 处 docstring 提及** ⇒ 残差就这一处 |
| 用例覆盖 | `git grep -ln enforce_scope_filter -- 'tests/*.py'` | 2 个文件：`test_execution_context_foundation.py`、`test_evaluation_framework.py` |

**为什么这一处不当场换掉（这是判据问题，不是难度问题）**：mock 对 `scope_type=PUBLIC` 的跨租户项**放行**，生产实现无 PUBLIC 例外、`scopes` 非空时还更严 ⇒ 换过去 `make eval` 的 golden 判分必变，等于**改评测基线**。红线是"测试红时不许收窄断言"，反过来"为了顺手统一而改动判分"同样不该由我在无方案下做 ⇒ 转 §3 第 21 项待拍板。

**本批实际改的两处**：① `evaluation.py` 里那句 `TODO: F01 … 落地后替换此函数` 已成**失效陈述**，订正为现状（已落地 + 只剩一处 + 不换的依据），零逻辑改动；② `docs/TODO.md` §4 F01 行**保持开项**、判据从"落地"收窄为"positive 路径那处替换 + 重取基线"，并声明 §0 索引「会展骨架 = 6」不受影响（现取：该段开项 6 / 闭项 0）。

**两处我自己写错又当场改掉的（写下来，别让它变成下一次的事实）**：
- 注释里我引了 `:91` 这个行号，而**我这段注释本身变长就把调用点推到了 `:94`**——行号会被自己的编辑顶掉，已改为按语句文本引用；
- TODO 行里我先写「与 §0.4『判据措辞欠账』同类」，`grep` 后确认那句话**只存在于本台账**（TODO §0.4 没有它）⇒ 死引用，提交前改成指向真实存在的 §3 第 21 项。这正好是 memory 里"修死引用要把路径与锚点分两层核"的又一次实证：**我这次是在写下的当下就错，不是文件后来漂移**。

**读数**：exhibition session **371 passed**（与加注释前同数 ⇒ 零行为变更），`ruff check applications/exhibition-agent` 全绿。

## 21. nl2sql-service 的 env 模板补齐 + 门禁（roadmap #21 / P2-5 第三处，2026-10-16，截止=当日）

**怎么找到的**：§19 里我为了划"能不能机械折算"的范围，全仓 `git grep BaseSettings` —— 命中第三个模型 `shared_schemas/settings.py::BaseLLMSettings`。
它自己不装模板，由 **`agent_server`（已钉）与 `nl2sql-service` 两个子类**承载 ⇒ 顺着去比 nl2sql 的模板，**这里就有真缺口**：
`Settings.model_fields` 折算出 **25** 个真实 env 名，模板只有 **13** 个 active 键 ⇒ **缺 12 个**，且成族：
`RERANK_*` 整族 4 个（rerank 默认关所以从没人发现它读不到值）、`LLM_TIMEOUT`/`LLM_MAX_RETRIES`、`VECTOR_DIM`（本服务覆盖基类 512→1536）、
`RETRIEVAL_TOP_K`/`RRF_K`、`SQL_MAX_ROWS`/`SQL_MAX_CORRECT_RETRIES`、`TABLE_PREFIX`。
**后果形状**：照模板部署时这 12 项静默取代码默认值 —— 与 §19 会展侧"模板有而代码无"是**对偶面**（那面是死键，这面是漏键）。

**交付**：① `.env.example` 末尾加 `# ===== nl2sql-service 模板补齐（2026-10-16）=====` 段，12 个键的默认值**逐条 1:1 取自 Field/类属性**（注释复用代码原话，含"为什么 top_k=10 而不是 agent_server 的 4"这类既有说明）；
② 新增 `applications/nl2sql-service/tests/test_env_template.py` 3 条（正向齐全 / 补齐段值等 + 段内不悬空 / 前提守卫无前缀无 alias）。

**两条口径要在用例里写死，否则会被误读成"覆盖比会展少"**：
- **反向死键判据只做在补齐段内**，不扩到全文件：本服务 `env_prefix` 为空，若照搬会展那条"模板里每个键都必须是字段"，会把经 `os.getenv` 读的键全打成死键——那需要全仓 `os.getenv` 扫描，仍属 §3 第 12 项待拍板。
- `PORT=8002` 与代码默认 `8000` **刻意不一致**（避开与 agent_server 抢端口，模板第 27-29 行已写明依据并引 `arch-audit-2026-09-24.md` P1-10），所以它留在 marker 段外、不参与等值比对。**这是设计不是漏检**；用例另有一条 `assert section` 防"补齐段被清空后用例空转"。

**非空转反证（3 条变异，全 RED 于正确理由）**：`VECTOR_DIM 1536→512` 击中值等断言 / 删 `RRF_K` 行击中正向齐全 / 段内加 `NOT_READ_BY_SETTINGS_AT_ALL=1` 击中段内不悬空。
模板文件按"备份字节→改→跑→写回"操作，`restore byte-identical: True`。

**读数**：nl2sql session **21 → 24 passed**（+3，既有用例零删改）；`ruff check applications/nl2sql-service` 全绿；`scripts/lint_architecture.py` 全绿；根/其余 session 不受影响（只动了一个应用的模板与新用例文件）。

**范围收口（这条线的终点在哪）**：全仓 pydantic-settings 模型现在**三处全覆盖**——`agent_server`（根模板 + 用例）、`exhibition-agent`（§19）、`nl2sql-service`（本批），
`shared_schemas.BaseLLMSettings` 作为被继承的基类**不单独装模板**，其键由两个消费方各自的模板承载 ⇒ 判据落在消费方，不在基类。
剩下 kefu / federation / knowledge-service 的配置面是 `os.getenv` + dataclass，**字段名推不出 env 名**，继续留 §3 第 12 项待拍板（人工枚举口径，不是门禁）。

## 22. 阶段 0 #2 闭合：完成证据格式规范件（2026-10-16，截止=当日）

**为什么它还算"未完成的计划"**：roadmap §二 阶段0 #2 的行是「无统一的完成证据格式 ⇒ 定证据规范：代码版本、执行命令、通过/跳过/未跑数量、所需依赖」，判据「规范入库并用于后续所有条目」。
`git grep "证据格式\|证据规范"` 全仓**只命中这一行本身** ⇒ 这条阶段 0 开项一直没被闭合，只是没人再提它。而本窗口 §12–§21 恰好产出了十几处"读数 + 反证"，格式已经在使用，只是没写下来。

**做法 = 从既有形态归纳，不新造流程**：先读 `docs/operations/evidence/2026-10-14-morning-state/readings.md`（现网回读的既有形状：rev 写在标题、"全部为回读不含推断"、目标×读数表、死端口对照组）与 `scripts/evidence/README.md`（可复现性判据），再落成 `docs/operations/evidence-format.md`：
五个必填字段 / 三条禁令 / 完成强度三档（已验证 · 标准环境已验证 · 待环境-待放行-待拍板）/ 新门禁的变异反证表 / 计数两口径与"多面标准逐面查写入点"。
§6 把规范逐条对到**已经用了它的六处台账 + 一处现网回读**，这就是判据里"用于后续所有条目"的可核对落点（不是自我声明）。

**入口**：`AGENTS.md` 验证策略段 + `docs/operations/testing-playbook.md` 段首各加一句指针（本手册管"怎么跑"，那份管"怎么记"）——按 memory 里"坑要落到仓库文档而非只落记忆"的既有分工，高频入口进 AGENTS.md，细节留在 operations。

**故意不做成 CI 门禁的那条（§7）与理由**：给了两条近似扫描命令（无 rev 的通过数、整体性名词），实测命中 184 / 182 行 —— 这个量级正说明它**需要语义判断**，机械报红只会训练人去措辞规避（AGENTS.md 框架规则条：约束应是减少犯错而非阻碍绕过）。要硬约束的地方已经硬了（`lint_architecture.py` 的 P/L 系列）。

**自查（本批我自己写错又当场改掉的三处）**：
① §7 的示例命令里我把 `[0-9a-f]{7,}` 用反引号包起来 —— 在 shell 里那是**命令替换**，命令会直接坏；改为无反引号写法并实跑通过。
② 我在 roadmap 阶段0 小计里先写「#3 的可交付部分已在 10-16 以书面结论形式给出」—— 实际那份对照法读数的留档日期是 **2026-10-14**，且判据要求的"真正连通取一次读数"**没有达成**；已改为"留档在案 + 本行保持开项"。**归因给自己方便的结果，是这类订正最容易漏的一种**。
③ CHANGELOG 里我把台账写成「§3 待拍板 20 行」，实际是 **21 行 = 真待拍板 20 项**（第 1 项作废保留编号），已按两个数分开写清。

**roadmap 阶段 0 三行的现状**（改在原文行内，按其既有范式，#6/#9 同款措辞）：**#1 达成**（§12 逐行命令级对账 + §16 对码下修 ⇒ "每条结论附代码位置与可复现命令"成立）、**#2 达成**（本件）、**#3 开项**（外部条件）。
小计 3 人/日 ⇒ **剩余 1 人/日**，口径 = **剩余 = 小计 − 已完成项原估工时**，不改写历史小计。

**验证**：`uv run python scripts/check_doc_sync.py` 需先 `git add` 新文档（存在性基准是 `git ls-files`，未入库即报红 —— 这条已在 AGENTS.md 记录）；本批零 `.py` 改动 ⇒ 测试面不受影响。

## 23. 对本轮两张台账做机械自审（不是目测）+ 复算脚本入库（2026-10-16）

**动机**：本窗口我自己写过 5 次错数（§12 那 4 处 + §17 的一处归因 + §19 的假缺口）。所以"改完自己审核"这一步不该再靠读一遍，而该靠**重算**。

**实算结果（全部一致，无漂移）**：
- `docs/TODO.md` §0 索引：0.1=4 / 0.2=4 / 0.3=**5 组求和 13** / 0.4=6 行在册（4 开项 + 2 条删除线已清零）/ 0.5=5 行；全文复选框 **open 25 / closed 14**，与段末两条 10-16 追记写的累计读数一致。
- 本台账：§3 编号行 **21** 条 = 表头声明 21 行 / 真待拍板 20（第 1 项作废保留编号）；§2 表 11 行。

**登记一条口径重叠、但不擅自重排**：TODO 0.3 标题写「全部『先方案后编码』、无外部条件依赖」，可它内嵌的会展 `F2 真实 LLM 连接` 自己标着「需产品决策输入」——按 0.1/0.2 的划法那更像一条「需拍板」项。重划要动多行且属分类口径决策 ⇒ 写进 §0 追记等方向，不在本批顺手搬（memory 里"提清理建议前先证伪自己的动机"同条）。

**复算做成可重跑的脚本**：`scripts/evidence/recount_todo_index.py`（收录判据=「会不会被下次必须重跑引用」，与本目录既有两份同族）。它必须处理两种表形态：一行一事项 vs **一行一组 + 「条数」列求和**（0.3 是后者，只数行会得到 5，声明是 13）。非空转反证：把 0.3 的声明从 13 改成 12 ⇒ 判 MISMATCH；一致时退出码 0、不符时 1。
**同样不做成 CI**：声明值写在标题里，改措辞就报红属噪声（`evidence-format.md` §7 的同类取舍）。

**本轮最该留下的一条教训（我自己踩的，而且是"看起来通过了"的那种）**：我先把复算写成一条 `uv run python -c "…"` 一行流贴进 TODO §0 的追记里，那串代码含 `'## 1. '` —— **它 split 到了自己所在的这段文字**，于是只读到文件前 921 字符，**输出空列表、exit 0**。如果我只看退出码，这条假通过就进仓库了。
发现方式不是复核逻辑，而是我把"要发布的命令"原样跑了一遍 ⇒ `[]`。三条推论写进 §0 追记与本节：
① **空输出 ≠ 通过**；② 判据命令若引用自身所在文件，必须避免与被搜文本同形（本次改为独立脚本落盘，从根上消掉自指）；③ 贴进文档的命令必须当场实跑，不实跑的命令不写进文档。

## 24. 阶段 2 再前移：把被我错分类的机械活捡回来（roadmap #21 / P2-5 收尾，2026-10-16）

**触发是一次对自己分拣结果的复查**，不是新需求：§3 第 12 项把两件不同的事捆在同一条"待拍板"里——
「要不要建**全仓双向门禁**」（是决策）与「把代码在读的键**补进模板**」（是机械活、零行为变更）。
捆在一起的结果是三家应用的模板一直没人动。按 objective「将未完成的计划进行完成」，后半截该由我做，不该等你拍板。

**扫描器两次返工（都是假阴性）**：
第一版把 `os.getenv(...)` 的函数名拼成 `os.getenv` 却拿集合里的 `"getenv"` 比对 ⇒ 几乎全漏——
实取 federation **read=5**、knowledge-service **read=0**（而 KS 树内 `git grep` 明有 93 个 `os.getenv` 站点）。
第二版补上 `os.environ[...]` 下标读法与 `from os import` 形态处理，并加了"扫到 0 个键即判用例空转"的自守卫 ⇒
实取 federation **75 键 / 3 动态名**、KS **75 键 / 2 动态名**、kefu **0 键**（kefu 确实不字面读 env，走 `.env`+配置文件装配）。
**这是今天第 5 次"探针错被当成事实"**，且前四次都发生在**我写下结论之后**而不是之前 —— 所以本批所有否定性/齐全性读数都带上了第二条通道（AST vs `git grep` 计数互校）。

**口径关键一条（决定缺口是 61 还是 17）**：这两家模板把可选开关一律写成**注释态** `# KEY=default`
（federation 文件里还自述"默认值取自代码中 os.getenv 第二参数"），那是刻意范式：开关不该带着值被部署生效。
所以判据必须是「**是否被提及**」，不是「是否为 active 键」：
按 active 口径实取 = federation 52 / KS 11（**假缺口**），按提及口径真缺 = **federation 7 / KS 10 = 17**。
我此前登记的「61 项（KS 13 / federation 47 / exhibition 1）」两头都不对：既用了 active 口径，又是人工清点。

**交付**：
1. `applications/agent_federation/.env.example` +7、`applications/knowledge-service/.env.example` +10，
   每行默认值取自 AST 实读的 `os.getenv` 第二参数并带 `<- 文件:行` 溯源；密钥类一律留空（`EVAL_JUDGE_API_KEY` / `RAGFLOW_API_KEY` 等），
   无默认值的显式标注"未注入即走未设置分支"；两文件字节约定（LF / 无 BOM）按原样保留，`git diff` 为 **25 added / 0 deleted**。
2. 新增 `tests/governance/test_app_env_templates.py` 2 条：**齐全**（代码字面量读取的键必须在模板被提及）+ **密钥键不得带可直接使用的值**。
   用例 docstring 里写死了上面的口径，并说明动态键名（5 处）不在覆盖范围、kefu 不入本表的原因（0 个字面量读取点，硬凑即空转）。

**非空转反证（三条，含两次探针自我纠错）**：

| # | 变异 | 结果 |
|---|---|---|
| 1 | 把 `MYSQL_CHARSET` 整条改名为未被提及 | `rc=1`，齐全用例报红 ✓ |
| 2 | 首版"密钥填真值形状"变异 | `rc=0` —— **但那是替换没生效的空操作**：锚点串与文件实际字节不符，我没断言"文件真的变了"就读了退出码 |
| 3 | 加 `assert 文件字节已变` 后重做 | 仍 `rc=0` ⇒ 暴露规则本身的洞：我用**子串**匹配占位词，测试值里恰好含 `xxxx` 被判成占位符放行 |
| 4 | 规则改为"整值精确匹配占位白名单 或 含 `<`"，再用长随机串 `sk-proj-A1b2…` 复跑 | `rc=1` ✓ 密钥用例报红 |

四步全部按"备份字节→改→跑→原字节写回"执行，末次校验 `restored: True`，`git status` 对两个模板只留 intended 改动。
**规则返工的两处都不是放宽判据凑绿**：① 初版"必须留空或含 <>"把本仓既有的 `your-key-here` 占位写法误判为违规；
② 子串版又对真实凭据形状失守。现版把"什么算占位符"写成显式白名单，并把两次误判的经过留在 docstring 里，供下次判同一件事。

**读数与未测项（说清边界，不含糊）**：
- `uv run pytest tests/governance/test_app_env_templates.py -q` ⇒ **2 passed**（本批新增）。
- `uv run pytest tests -q -m "not requires_pg"` ⇒ **720 passed / 29 deselected**。这一条只覆盖 `tests/`，**不等于 CI 的第 1 个会话**——
  由此发现并订正了 §18 会话 1 的标签错误（CI 用 `testpaths = tests + packages/agent-core/tests`，故 §18 记的 1067 里含 agent-core 的 ~347 条）。
- **CI 等价的根会话本轮未重跑**（命令 `uv run pytest -q -m "not requires_pg"` 被用户中止）⇒ 「根会话 1067 → 1069」目前只是**推断**（只新增一个测试文件、零产品代码改动），不是实测。对外引用前需补跑这一条。
- 其余 9 个会话本批未跑；`ruff check` 新文件全绿。

**§3 第 12 项相应收窄**：剩下的只有「要不要建**全仓双向门禁**（模板键 ⇔ 代码读取，含动态键名与跨包共享层读取）」这一件决策，
外加「kefu 这种 0 字面量读取点的应用要不要另设判据」；"补模板"这半截已从待拍板里拿走并完成。
