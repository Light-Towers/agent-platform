# 技术锚点对照表｜生产交付推进计划配套

> 配套文件：`docs/plans/plan-production-delivery-roadmap-2026-10-09.md`（正文一律说人话，不含代码路径与英文缩写）。
> 用途：把正文里的说法映射回代码与文档位置，供对账、复核、开工时定位。**汇报场合不需要本文。**
> 维护：正文措辞变化时改本文对应行；正文出现新的技术说法时补行。本文行不改变任何结论。

| 正文说法 | 对应技术实体与位置 |
|---|---|
| 运行时 | `packages/agent-runtime`（admission / scheduler / coordinator / checkpoint / planner / skills / memory / sandbox / forensic / cost_governance / identity） |
| 内核 | `packages/agent-core` |
| 共享数据定义 | `packages/shared-schemas` |
| 6 个服务 | `applications/`：agent_server · agent_federation · knowledge-service · nl2sql-service · kefu-service · exhibition-agent |
| 防覆盖保护 | generation fencing 已覆盖 3/5：`planner/durability_pg.py` L113–146（`PgCheckpointStore`）+ L215–274（`PgExecutionOwnershipStore`，takeover 时 generation+1）、`execution_state_pg.py` L85–110（`PgExecutionStatusStore`，SQL 层原子拒绝）。缺：`awaitable_task_pg.py`（全文 0 处 `generation`）与 `planner/durability_pg.py` 的 `PgSideEffectStore` |
| 同名任务回执存储两份实现（本轮新发现） | `PgAwaitableTaskStore` 同时定义在 `awaitable_task_pg.py:23` 与 `execution_state_pg.py:114`；生产侧只 import 前者（`main.py:352/354`），后者除模块内 `__all__` 外全仓零调用（`working_memory.py:102` 的提及在 docstring 用法示例里，不是调用）⇒ 后者为死码。**去重判据**：`packages/agent-runtime/tests/test_awaitable_task.py` 只覆盖 InMemory 变体，**两份 PG 实现都无测试直接覆盖**，故不能写「保留有测试的那份」，应以生产实际 import 的那份为基线 |
| 4 个未接线模块 | `execution_recovery` / `human_task` / `payload_externalization` / `state_migration`（均标 `**STATUS: NOT WIRED**`）+ `applications/exhibition-agent/exhibition_agent/foundation/skill_router.py:5`。全仓递归实测就这 5 处。**注意**：`forensic` / `effect_contract` / `skill_lifecycle` 在 applications 层零 import，但被运行时生产链内部调用（`planner/execution_graph.py:23-24`、`planner/protocol.py:34-35`、`skills/registry.py:244` 拒绝 RETIRED 能力注册）⇒ **不是孤岛，不计入未接线** |
| 新规划引擎 | graph planner（`applications/agent_server/config.py` 当前默认 deterministic） |
| 隔离门卫 | IdentityMiddleware，ADR-0006 / ADR-0007；强制开关 `DEPLOY_ENFORCE_IDENTITY`、`TENANT_JWT_ENFORCE` 默认关 |
| 自动检查门禁 | `scripts/lint_architecture.py`。**2026-10-09 实测三口径（数值已被后续新增规则推翻，见本行末）**（已回写 `ARCHITECTURE.md` §4.1）：文档表 **15 行**（原只列 P 系列 11 行，L 系列 4 条漏登记，本轮已补齐）/ `main()` 打印门禁编号 **14**（P4-2/P2/P5/P6/P7/P8/P9/P10/P11/P12/L-3/L-1/L-2/L-4；P6-3 并入 P6 打印）/ 实现函数 **16**（`check()` 承接 P4-2 + 15 个 `check_*`，其中 P6 与 P7 各由两个函数合并打印）。旧文档的「7」无来源，已作废。**L 系列详情**：L-3 `check_init_scatter`、L-1 `check_manual_cm_lifecycle`、L-2 `check_tracer_state_scatter`、L-4 `check_otel_extras_alignment`，全仓 `test_*.py` 对这四个函数**零引用**⇒ 无独立治理用例（判据即 lint 自身，靠 `make lint`/CI 常驻） | ｜ **2026-10-16 现值**：文档表 **17 行** / 门禁编号 **16**（+L-5 #12、+P13 #11）/ 实现函数 **17**。这三口径会随规则增减变化，`check_doc_sync.py` 管不到 ⇒ 每次加规则须同时改 `ARCHITECTURE.md` §4.1、capability-map、讲解稿与本行。
| 健康检查 | `applications/agent_server/api/health_router.py`（10-09 取证时缺 scheduler / control_plane / cost_governance / forensic）。**已被次日提交取代：`18b6954`（2026-10-10）补齐四字段 + 契约测试 `applications/agent_server/tests/test_health_fields.py`；2026-10-14 本机实跑 14 passed、响应实测 25 键（基类 13 + app 独有 12）。本行保留为 10-09 历史取证，不外引** |
| 记忆加固 | `docs/plans/plan-memory-hardening-2026-09-27.md`（T2–T8，缺口 G2–G10）。**2026-10-09 实测修正（四个行号逐个实读复核为真）**：模糊匹配属实（`memory_pg.py:70` 用 `ILIKE`）；**按条删除已有且已装配**（`memory_pg.py:122` 按 episode_id、`:249` 按 name+version；`main.py:91-94 / 127-130` 两处 import 并构造 `PgEpisodicStore` / `PgProceduralStore`）；**来源标注已有但未装配**（`semantic_memory.py:125/134` 写 `r.source = "shared"` / `"user"` 为实代码非 docstring，`memory_types.py:57` 有 source 字段；但全仓 `SemanticMemory(` 除其自身 docstring 示例外**零出现**⇒ 无生产调用点）；去重与语义检索**代码已存在但未装配**（`episode_dedup.py` 共 17 处引用，除定义与 `__all__` 外全在两个测试文件；`embedding_recall.py` 存在但生产侧零 import）⇒ 本项从「新建」降为「装配 + 补混合检索」。**已证伪的旧说法**：不存在 `agent_runtime/memory/` 子包（记忆模块平铺在包根），也不存在 `WorkingMemoryStore` / `EvidenceStore` 两个类名（全仓 `.py` 零命中），不得再用 |
| 语义记忆无生产实现（正文 #20） | `packages/agent-runtime/agent_runtime/semantic_memory.py:54 SharedSemanticStore`、`:66 UserSemanticStore` 均为 `abc.ABC` + `@abc.abstractmethod`；全仓 10 处引用 = 定义 2 + 类型注解 2（`:105/:106`）+ `__all__` 2 + **测试替身两个子类**（`tests/test_memory_types.py:145/150`）⇒ 生产实现 **0 个**；另 `SemanticMemory(` 唯一出现处为自身 docstring（L97）⇒ 门面本身也未接线。缺生产实现的是**两个**（`SharedSemanticStore` 与 `UserSemanticStore`），正文早先写成 1 个，已改 |
| 打分门禁 | `eval/`（golden 15 题，Makefile L54 `--fail-below 0.8`）。**2026-10-09 实测**：检索类基线**已冻结入库**（`applications/knowledge-service/eval/baselines/e2e_post_sparse_fix_2026-09-29/`，CI 已指向该锚点）；`eval/baselines/planner_*.jsonl` 两份仍在但读数停留在 2026-08-21；联邦漂移基线 `evaluation/fed_latest.jsonl` 因无 LLM 密钥生成不了（TODO §0.1 B 类第 2 条）；平台自题 golden 共 3 份 28 条（15 + 8 + 5） |
| CI 命令 | `make ci` = lint + 10 组 pytest + eval + `uv lock --check`（Windows 无 make，用等价 `uv run` 命令） |
| 故障注入 | `tests/ha/`（不变量 I1–I7）+ `scripts/ha_real_kill_verify.py` + `deploy/k8s/scripts/e2e_traceparent.sh` |
| 存量库升级核查 | `docs/plans/plan-isolation-hardening-2026-09-27.md` §8 pre-flight（migration 006） |
| 真实集群验收 | `deploy/k8s/VERIFICATION.md`：L94/L112 实测节点驱逐自愈 **8.4s（另一次 6.2s）**，L4 写“**L0-L5 全部达标**”。⇒ 正文口径必须区分：**编排层已验收**，**未验收的是 V3 执行层端到端双实例物理故障转移**（TODO §2 唯一开项 + `AGENTS.md` 红线），不可笼统写“高可用未验收” |
| 强杀脚本（正文 #16） | `scripts/ha_real_kill_verify.py:35` 已读 `AGENT_PLATFORM_PG_URL`，**本机 localhost:5433 仅为默认值**⇒ “硬依赖本机库”说法不准，真实问题是未注入时会静默默连本机 ｜ **2026-10-16 已按后半处置**：默认 DSN（含内嵌凭证）删除，缺失即退出码 4 拒跑；行号已漂移，现以 `_require_pg_url()` 为锚，门禁 `tests/test_ha_kill_script_gate.py` |
| 性能遗留（正文 #19） | `docs/tech-debt/tech-debt-audit-2026-09-22.md` §三 P1：**6 张向量表缺 HNSW 索引**（`agent_runtime/db.py:17-189`）+ P2/P3 两处 N+1 串行往返。旧口径“2 处全表扫描”无出处，已作废 |
| 接口遗留（正文 #21） | `docs/plans/arch-audit-2026-09-24.md` L19：P2 共 7 项含 1 项复核撤销 ⇒ **有效 6**（P2-1 死代码 skill_router、P2-2 singleflight 竞态、P2-3 WS 未接中间件、P2-5 `.env.example` 与代码不匹配、P2-6 文档口径矛盾、P2-7 MinIO 失败仅 warning）。旧口径“3 处接口保留”无出处，已作废 |
| 失败自动处置（正文 1.1「只做了一半」） | 队列层：`execution_scheduler.py:615 SchedulerReaper` 在生产 `main.py:414–416` 显式 `start()`（lease-based，依赖 ownership_store）。执行层：`execution_recovery.py` 的 `Reaper` / `RecoveryManager` / `Rescheduler` 仅被本包单测 `packages/agent-runtime/tests/test_execution_recovery.py` 引用，applications 层零调用（模块头标 NOT WIRED）⇒ 「一半」的分界在**回收（已接）vs 恢复决策（未接）**。另：`SchedulerReaper.run()` L645–668 的动作只是「lease 失效 → `complete(FAILED)` 释放槽位」，**不重新排队** ⇒ 卡死任务会被标失败而不会自动重跑（reschedule 属未接线的 `Rescheduler`）。**命名撞车提醒**：`execution_recovery.Reaper` 与 `execution_scheduler.SchedulerReaper` 是两个类，grep `Reaper` 会同时命中，不可据此判「回收已接线」 |
| “已进主干”日期（本轮纠正） | `execution_scheduler` / `cost_governance` / `skill_lifecycle` / `forensic` / `control_plane` 均于 **2026-09-23 `37d9342`** 进入，已验为 `main` 祖先（`git merge-base --is-ancestor` 返回 YES）；**PR #41（2026-10-01）不含任何一个调度类文件**（带的是身份层）⇒ 正文旧日期 2026-10-01 错归。**口径提醒**：这些能力均在 `scheduler_enabled` 开关内（默认 False），所以下说法写「已进主干且已接线，总开关默认未打开」而非「已生效」 |
| 用户界面（正文 1.1） | `git ls-files` 实测 `package.json` / `.vue` / `.jsx` / `.tsx` **入库数均为 0**；入库 `.html` 共 4 个：会展 `static/index.html`、知识库 `import.html` + `chat.html`、`docs/architecture/overview.html`（文档产物）。⇒ 不可写“全仓无前端入口”，应写“无交付级界面工程” |
| 容量压测入口 | `applications/knowledge-service/benchmark/locustfile.py`（自述不预填实测数字、不承诺 QPS） |
| 内网被占用 | Clash TUN 接管 192.168.100.0/24；PowerShell `TcpTestSucceeded=True` 不含信息，须用死端口对照法 |
| 待办清单 | `docs/TODO.md`。**2026-10-09 实测**：`[ ]` 开放 30（与文档自记 B4+C4+D16+E6=30 一致）/ `[x]` 已关 9（顶格与含缩进同值；文档内登记口径写 closed 8，差 1 属口径不一致）。§2 缺口 1–10 为本轮逐条对账对象，逐条结果见下节 |
| 接口约定 | `docs/architecture/cross-project-interface-contract.md`（348 行；v1.3；C1 身份 / C2 调用 / C3 人工确认 / C4 trace / C5 分级；**待决 D1–D7 实测 7 项** L320–326；状态"🟡 草案 · 待双方确认" L12；**§5 验收 8/9 勾** L335–343，未勾项正是“写请求必带 HITL + Idempotency-Key”）。**本轮新发现漂移**：正文已升 v1.3，但 L97 传输章节仍写 `X-Contract-Version: 1.2`（缺失按 1.2 处理）⇒ 版本头与契约版本不一致 |
| 已接两家业务系统 | `applications/exhibition-agent/skills/` 下 exhibition-readonly（SKILL.md L12 自记“产品侧共 **13 个 skill / 48 个 tool**”、L47 表行编到 13；PARTIAL / SYNTHETIC / READY 三档标注）与 mingyang-venue-ops（L56 带权实测：**56 个 sys 端点中 38 个返回 200**，2026-09-18；`live.manifest.json` 的 `assertions` 数组**实测 38 条**，非“约 40”）。另：会展 `golden_cases.json` 实在 `skills/exhibition-readonly/tests/` 下，**api_contract 22 + prompt_routing 6 = 28 条** |
| 「接一家就能自动跑一遍验证」的工具（正文 §5.2 #1 / §5.4 #1 的「六类检查」） | 设计在 `skills/mingyang-venue-ops/SKILL.md` L193–234「回归测试（只读能力门禁 · 三层）」：L1 结构断言（八组 A 鉴权 / B1 全局 / B2 默认展会作用域 / C 带 exhibitionId / D sys 边界含 401 / E 写护栏 `write_calls=0` / F.company / G.portal）、L2 黄金主（归一化结构指纹）、L3 气隙回放（cassette + `SKILL_HTTP_MODE=replay`）。正文「六类」= 语义归并：凭证有效←A、连得上且有数据←B1/B2/C、结构漂移←L2、权限边界←D 的 401 组、误发写请求←E、断网重跑←L3；**F/G 是同一层按子系统的分组，不是额外类型**。清单 `live.manifest.json` 已入库；执行器 `tests/skill_live_check/`（harness.py / GOLDEN_MASTER.md / tasks.golden.json / `golden/` 说明书自记 33 个 / `cassettes/` 自记 80 个）**三通道均确认不存在**：版本库清单命中 0 + 本机目录不存在 + 全仓递归找不到文件 ⇒ 「验什么的标准在库、跑标准的执行器不在库」。`base_url` 为内网 `192.168.100.9`，本机受代理接管所阻 |
| 说明书读取工具 | `applications/exhibition-agent/exhibition_agent/skill_loader/parser.py`：L23 正则硬编码 `/api/` 与 `{EXHIBITION_API_BASE_URL}`；**本轮新发现** L267 写死了某开发机的本机绝对路径（`D:\0-mingyang\code\...`）作为说明书查找路径之一；名称表实有 **49** 条（比 48 多一条，含 `/api/health`） |
| 5 个通用能力注册 | `applications/agent_server/capabilities.py` `_register_remote_skills`（URL 为空静默跳过；仅 knowledge 带 Bearer） |
| 借用真人登录凭证 | 场馆说明书 `MINGYANG_JWT`（浏览器会话令牌，约 13 天过期，需同源 Referer，写操作落真实生产账号） |
| 返回成功但内容写着失败 | 场馆实测：GET 调 POST 端点 → HTTP 200 但 body `code=500`。**注意（本轮审查订正）**：不存在「workorder ok-but-failed 评审文档」与「inband 错误对照表」（`docs/reviews/` 实际只有 2 个文件，README 全文无 `ok-but-failed`/`inband`/「对照表」字样）⇒ 正文不得引用该实体，只引场馆实测那一条 |
| 可信度默认值 | 接口约定 C2 映射表"readiness 缺失默认 READY"（fail-open），与同约定 C5"未分级按 CONFIDENTIAL"（fail-closed）方向相反 |

## 附录 A｜待办清单 §2 缺口 1–10 逐条对账（2026-10-09，本轮正文引用的“附录对照表”即本节）

> 逐条仍读代码取得，不依赖本机环境、未跑测试。“TODO 过时”= 待办清单记为缺口但代码已完成，属重复建设风险。

| 缺口 | 待办清单的说法 | 实测结论 | 证据位置 |
|---|---|---|---|
| 1 | 严格 Fencing 需覆盖 5 类 durable write，当前仅防 checkpoint stale write | **部分（3/5）** | 见上「防覆盖保护」行：checkpoint / scheduler ownership / execution status 三类有 fencing；awaitable receipt 与 side effect 两类无 |
| 2 | `SideEffectStore` ≠ 语义契约，缺 delivery/retry/recover 分类 | **已完成**（TODO 过时）——仅指契约本身 | `effect_contract.py` L36 `DeliverySemantics` / L60 `RetryPolicy` / L68 `FailureRecovery` 三分类齐全，且被 `planner/protocol.py:34-35` 调用。**边界**：按该契约做恢复决策的 `RecoveryManager` 仍在未接线的 `execution_recovery.py` 里⇒ 「契约已生效」不等于「恢复已生效」，不得混用 |
| 3 | External Task + Receipt 未独立持久化，crash recovery 无法查外部系统真实状态 | **部分**：已独立持久化，但恢复路径不查 | `main.py:352/354` 装配 `PgAwaitableTaskStore`；恢复查询依赖 `execution_recovery.py`（标 NOT WIRED） |
| 4 | Execution Scheduler 缺 priority / fairness / backpressure / stuck / reschedule | **部分**：前四项已完成，`reschedule` 未接 | 已接：`execution_scheduler.py` L9 与 L15–17 三级排序（priority → per-tenant fairness → FIFO）、L116 `QueueFull`、L309 `FOR UPDATE SKIP LOCKED`、L615 `SchedulerReaper`（已 `start()`，仅标 FAILED 不重排）。未接：`Rescheduler` 在 `execution_recovery.py`（NOT WIRED）⇒ 本项不得计为已完成 |
| 5 | Durable Execution Status State Machine | **已完成**（TODO 过时） | `execution_status.py` 10 态状态机 + `execution_state_pg.py` L85–110（SQL 层原子拒绝旧 generation） |
| 6 | State Schema Version / Migration（V3-6 Layer B） | **未接线** | `state_migration.py` 标 `STATUS: NOT WIRED` |
| 7 | Large Payload Externalization（V3-6 Layer B） | **未接线** | `payload_externalization.py` 标 `STATUS: NOT WIRED` |
| 8 | Control Plane 缺 pause/resume/cancel/retry/requeue/recover/inspect/terminate 可操作面 | **部分**：8 项中 6 项有，缺 `requeue` 与 `recover` | `control_plane.py` L97 inspect / L162 pause / L183 resume / L204 cancel / L241 retry / L272 terminate |
| 9 | Replay Forensic：Trajectory 未记录 model/prompt/skill/policy version | **已完成**（TODO 过时） | `forensic.py` 已带 model / model_version / prompt_version / skill_version / input / tool / planner / policy_version |
| 10 | Skill Version / Lifecycle / Compatibility | **已完成**（TODO 过时） | `skill_lifecycle.py` + `skills/registry.py:244`（拒绝 RETIRED 能力注册） |

**小结**：已完成 4（缺口 2/5/9/10）· 部分 4（1/3/4/8）· 未接线 2（6/7）⇒ 正文阶段 0 与 #1 的「4 完成 / 4 部分 / 2 未接线」口径成立。

**两数自行修正记录**（不粉饰）：① 本表初数曾得 4/4/2，成因是把缺口 2 归入“部分”；读 `effect_contract.py` 确认 delivery/retry/recover 三分类齐备后改为 5/3/2。② 随后读 `SchedulerReaper.run()` 发现它只标 FAILED 不重排队，`Rescheduler` 仍在未接线模块 ⇒ 缺口 4 从“已完成”降为“部分”，回到 **4/4/2**。两次修正均由实读驱动，结论以本表为准。
