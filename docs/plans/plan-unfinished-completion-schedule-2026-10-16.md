# 排期：未完成计划的收口计划与截止完成日期（2026-10-16）

> 状态：**现行执行排期**（本文件只做「排期 + 已核实进度 + 需拍板清单」，不重复各 plan 的技术方案；技术方案仍以各 plan 为准）。
> 制定日期：2026-10-16 ｜ 分支：`chore/tech-debt-agentic-discovery-test-2026-10-15` ｜ **本批不部署**（夜间 126 关机）。
> 上游锚点：`plan-production-delivery-roadmap-2026-10-09.md`（计划窗口 **2026-10-09 ~ 2026-12-04**，合计 84 人/日，其中 **8 人/日「待环境」，按 roadmap 自身规则不可承诺日期**）。
> 口径纪律：本文所有「已完成」均以**代码 + 测试实跑**为据（逐条附提交号），不以文档状态行、不以复选框、不以口头汇总为据。

## 0. 截止完成日期（先给结论）

| 层 | 截止日 | 内容 | 可否承诺 |
|---|---|---|---|
| **阶段 0 收口** | **2026-10-16**（今天，即 roadmap 原定窗口末日） | 待办清单与代码对齐、逐条补证据 | ✅ **已收口（10/16）** |
| **阶段 1 平台收口（本排期主目标）** | **2026-10-30** | 下文 §2 表中「我可独立执行」各行 | ✅ **本地可执行行已于 10/16 全部做完**（提前 14 天）；剩「待环境」行（#4 真库拒绝用例、#8 根因再现）不可承诺日期 |
| **阶段 2 提前开工（§7）** | **2026-10-19**（#12 观测装配门禁） → 后续行另排 | 把阶段 2 中**不依赖 126/密钥/真库**的行前移，避免 10/17–10/30 空转 | ✅ 可（#12 判据本地可验） |
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
| 10/28–10/30 | **阶段 1 收口对账**：逐条按 roadmap「怎么算改好」列复核 + 全量门禁（`ruff check .` / `check_doc_sync.py` / 相关 pytest session） | roadmap 阶段1 | 文档 | 每行有代码或测试依据；待环境行明确标注「标准环境已验证 / 多物理机待环境」 | 我可独立执行 |
| — | **待环境（只登记，不承诺日期）** | #4 真库两类拒绝用例、#8 KS 15 条报错根因 + 图谱重测、V3 双实例物理故障转移、CodeQL B7b-4/5 重扫、env-var 126 部署脚本同步 | 需 126/PR/CI | roadmap §四第 2 条规则 | 环境解锁后 |

## 3. 需要用户拍板（**请在 10/20 前给方向，否则将阻塞 §2 后半**）

红线「所有代码优化/重构必须先制定方案」+ 我不替你做设计决策。以下 5 项方案已就绪，卡在「选哪条路」而非「有没有路」：

1. `plan-audit-operator-principal-2026-10-03.md` — 审计主体改造是否开工（现：方案已写、零代码）
2. `plan-m11-exception-classification.md` — 状态 `Proposed`，接受 / 修改后再施工
3. `plan-router-keyword-gate-hides-corpus-2026-10-12.md` — 修法三选一
4. `plan-v3-phase-2-4-integration-2026-09-23.md` — v2 方案（含 6 项不变量）确认后施工
5. tech-debt 补充 4 — agentic bridge 默认开 vs 保留 opt-in 但补开启路径测试
6. **#7 对外 `/health` 三套约定是否统一**（评估结论见 §6）——统一到共享 `HealthStatus` 需改 exhibition/kefu/knowledge 的**线上响应值**，且 knowledge-service `/health/ready` 的 503 是就绪探针语义的一部分。本轮只交付不破坏下游的一致性测试 + 禁第 4 套护栏；统一与否请你定（选项：a 全统一到 `HealthResponse` / b 仅新增服务强制、存量保留并在看板侧做映射 / c 保留现状仅靠测试钉住不再扩散）。

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
- 附带查得：本仓个别源文件带 **UTF-8 BOM**，`ast.parse` 在 `utf-8` 下抛 `SyntaxError` ⇒ 测试统一用 `utf-8-sig` 读，避免以"环境噪声"失败。
- 判据「跨服务一致性测试」已具备；「打分测试不破坏下游」= 未动任何对外 body，`eval/run_eval.py` 门禁不受影响。
