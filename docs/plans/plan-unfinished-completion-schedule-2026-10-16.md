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
| — | **待环境（只登记，不承诺日期）** | #4 真库两类拒绝用例、#8 KS 15 条报错根因 + 图谱重测、#16 第二半（双机接管+防覆盖+过载保护场景在真库通过）、V3 双实例物理故障转移、CodeQL B7b-4/5 重扫、env-var 126 部署脚本同步 | 需 126/PR/CI | roadmap §四第 2 条规则 | 环境解锁后 |

## 3. 需要用户拍板（**请在 10/20 前给方向，否则将阻塞 §2 后半**）

红线「所有代码优化/重构必须先制定方案」+ 我不替你做设计决策。以下 **17 行**（按本表条目计数，非按 plan 文件数）方案已就绪，卡在「选哪条路」而非「有没有路」：
**其中真待拍板 = 16 行** —— 第 1 项经 2026-10-16 对码作废（代码早已合入，见该行注），作废行的编号保留不复用；第 17 行按行计 1、内含 5 问（三份 ADR 各 §5）。

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
    **待你定的只剩两件**：① 剩下 **61 项**（KS 13 / federation 47 / exhibition 1；口径与两个盲区见 §10 P2-5 ②）要不要补；② 要不要做**全仓双向门禁**（"模板键 ⇔ 代码读取"，需先解决共享层读取与 `env_prefix` 折算两个扫不到的面）。
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
- 附带查得：本仓个别源文件带 **UTF-8 BOM**，`ast.parse` 在 `utf-8` 下抛 `SyntaxError` ⇒ 测试统一用 `utf-8-sig` 读，避免以"环境噪声"失败。
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
| #13–#15、#17–#20、#22–#23 | 见各行 | 依赖真库 / LLM 密钥 / 126 / 集群 / 前端方案评审 | ⛔ **待环境或待拍板，不承诺日期**（§3 现列 **17 行**、其中真待拍板 **16 行**（第 1 行经本轮对码作废；第 17 行内含 5 问），**10/20 前**要给方向。第 15 行 = 本表 #5 那格暴露的判据措辞问题，第 16 行 = embedding 旁路（本轮新登记），第 17 行 = §13 三份 ADR 的选型问）；**#24 例外**：它的「各出决策记录」半已于 10/16 交付（§13），剩下的是那 5 问的答案 + 「文档与代码指向一致」的全量盘点 |

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
